import logging
import uuid
import json
import time
import dspy
from typing import Any, Dict, List, Optional

from agents_sdk.core.agent_executor import AgentResult, AgentTask, Context
from agents_sdk.core.main import main
from agents_sdk.core.his import HisClient
from utils.dspy_aios_llms import AIOS_DSPy_LMs
from utils.hierarchical_agents_models import BudgetEstimate, TeamOutcome
from utils.json_utils import extract_json

log = logging.getLogger(__name__)

NODE_ID_MAPPING = {
    "agent-workflow-arch-design-team-lead": "my-company-arch-design-team-lead-agent",
    "agent-workflow-arch-junior": "my-company-arch-junior-agent",
    "agent-workflow-arch-senior": "my-company-arch-senior-agent",
    "agent-workflow-cos":"my-chief-of-staff-agent"
}

# --- 1. The Signatures ---

class ArchEstimationSignature(dspy.Signature):
    """
    ### ROLE
    You are the Arch & Design Team Lead.

    ### TASK
    Estimate the budget and effort for architecture planning and system design.
    
    ### OUTPUT
    Output EXACTLY a JSON block: {team_name, amount, deliverables}
    """
    problem_statement = dspy.InputField(desc="The product idea")
    budget_estimate = dspy.OutputField(desc="JSON matching BudgetEstimate schema")

class ArchExecutionSignature(dspy.Signature):
    """
    ### ROLE
    You are the Arch & Design Team Lead.

    ### TASK
    Produce the final architecture design and system blueprint.
    
    ### OUTPUT
    Output EXACTLY a JSON block: {team_name, deliverables: List[str], status: str, blueprint: str}
    """
    problem_statement = dspy.InputField(desc="The product idea")
    specialist_contributions = dspy.InputField(desc="Inputs from Senior and Junior architects")
    team_outcome = dspy.OutputField(desc="JSON matching TeamOutcome schema")

# --- Helper Classes ---

class AgentPayloadProcessor:
    def prepare_payload(self, task: AgentTask):
        data = task.job_data
        if not isinstance(data, dict):
            data = {}
        if "initial_input" in data and isinstance(data["initial_input"], dict):
            data = data["initial_input"]
        raw_text = data.get("text") or data.get("user_request") or ""
        communication_type = data.get("communication_type", "delegate")
        model_name = data.get("model_name", "aios:qwen3-1-7b-vllm-block")
        session_id = data.get("session_id", str(uuid.uuid4()))
        return raw_text, communication_type, model_name, session_id

class ModelContextManager:
    def __init__(self, aios_dspy_lm: AIOS_DSPy_LMs):
        self.aios_dspy_lm = aios_dspy_lm

    def get_context(self, model_name: str, session_id: str):
        return dspy.settings.context(
            lm=self.aios_dspy_lm.get_choosen_model(
                model_name=model_name,
                session_id=session_id
            )
        )

# --- 2. The Arch & Design Team Lead Agent ---

class ArchDesignTeamLeadAgent:
    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        self.persona_default_system_message = getattr(self.subject.persona, 'default_system_message', "") if hasattr(self.subject, 'persona') else ""
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        
        self.payload_processor = AgentPayloadProcessor()
        self.model_context = ModelContextManager(self.aios_dspy_lm)
        self.task_registry = {}
        
        # Initialize HIS Client
        his_config = getattr(self.subject.persona, 'config', {}).get("parameters", {}).get("HIS_CONFIG", {}) if hasattr(self.subject, 'persona') else {}
        self.his_client = HisClient(
            base_url=his_config.get("HIS_BASE_URL", "http://localhost"),
            poll_interval=his_config.get("HIS_POLL_INTERVAL", 1.0),
            max_wait=his_config.get("HIS_MAX_WAIT", 60)
        )

    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        log.info(f"Preprocessing task {task.task_id} {task.job_data}")
        data = task.job_data
        if not isinstance(data, dict):
            data = {}
        task_type = data.get("task_type")
        if not task_type and "initial_input" in data and isinstance(data["initial_input"], dict):
            task_type = data["initial_input"].get("task_type")
            
        if task_type not in ["estimate_budget", "execute_task", "final_blueprint"]:
            log.warning("Task %s has task_type %s, which is not architecture lead action, skipping Arch Lead.", task.task_id, task_type)
            return None
        return [task]

    def _log_to_his(self, target_id, job_data):
        try:
            source_id = getattr(self.subject.identity, 'subject_id', 'unknown')
            target_id_mapped = {v: k for k, v in NODE_ID_MAPPING.items()}.get(target_id, target_id)
            msg = {"text": str(job_data), "source_id": source_id, "destination_id": target_id_mapped, "team": "Architecture Team", "timestamp": time.time()}
            self.his_client.submit(input_data=msg)
        except Exception:
            pass

    def get_muxer(self):
        return None

    def on_data(self, task: AgentTask) -> AgentResult:
        try:
            data = task.job_data
            if not isinstance(data, dict):
                data = {}
            if "initial_input" in data and isinstance(data["initial_input"], dict):
                log.info("Unpacking dynamic router payload in Arch Lead")
                data = data.get("initial_input", {})

            history      = task.job_data.get("history", [])
            outputs      = task.job_data.get("outputs", {})
            initial_input = task.job_data.get("initial_input", {})
            last_executed = task.job_data.get("last_executed")
            last_executed_batch = task.job_data.get("last_executed_batch")
            final_blueprint = ""
            # if last_executed_batch:
            #     last_node = [node["nodeID"] for node in last_executed_batch]
            # elif last_executed:
            #     last_node = [last_executed["nodeID"]]
            # else:
            #     last_node = []
                
            task_type = data.get("task_type", "estimate_budget")
            task_id = data.get("task_id", task.task_id)
            user_request = data.get("user_request")
            priority = data.get("priority", "Fast")

            last_node = None
            if last_executed and "output" in last_executed and "final_blueprint" in last_executed["output"]:
                final_blueprint = last_executed["output"]["final_blueprint"]
                last_node = last_executed["nodeID"]
                task_type = last_executed["output"]["task_type"]
            
            raw_text, communication_type, model_name, session_id = self.payload_processor.prepare_payload(task)
            # Re-read parameters from unpacked data
            communication_type = data.get("communication_type", communication_type)
            model_name = data.get("model_name", model_name)
            session_id = data.get("session_id", session_id)
            llm_session_id = session_id

            if task_id not in self.task_registry:
                self.task_registry[task_id] = {"user_request": user_request, "priority": priority}
            else:
                if user_request:
                    self.task_registry[task_id]["user_request"] = user_request
                if "priority" in data:
                    self.task_registry[task_id]["priority"] = priority

            # Extract problem_statement from text
            text = data.get("text")
            extracted = extract_json(text) if text else None
            problem_statement = extracted if isinstance(extracted, dict) else (text or data.get("problem_statement") or raw_text)

            if task_type == "estimate_budget":
                return self._handle_estimation(task, task_id, problem_statement, llm_session_id, model_name, communication_type)
            
            elif task_type == "execute_task":
                return self._handle_execution(task, task_id, problem_statement, llm_session_id, model_name, communication_type)

            elif task_type == "final_blueprint":
                # Senior sends this back when debate is finished
                return self._handle_final_blueprint(task, task_id, final_blueprint, llm_session_id, model_name, communication_type)

            return AgentResult(task_id=task.task_id, skip=True)

        except Exception as e:
            log.exception(f"Error in Arch Team Lead: {e}")
            return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})

    def _handle_estimation(self, task, task_id, problem_statement, session_id, model_name, comm_type):
        with self.model_context.get_context(model_name=model_name, session_id=session_id):
            module = dspy.ChainOfThought(ArchEstimationSignature)
            result = module(problem_statement=json.dumps(problem_statement))
            
            be_raw = result.budget_estimate
            be_data = extract_json(be_raw)
            
        job_data = {
            "task_type": "budget_estimate",
            "budget_estimate": be_data,
            "task_id": task_id,
            "user_request": self.task_registry[task_id].get("user_request"),
            "communication_type": comm_type,
            "session_id": session_id,
            "model_name": model_name
        }
        
        # Globally store deliverables for execution phase
        self.task_registry[task_id]["deliverables"] = be_data.get("deliverables", [])
        
        self._log_to_his("my-chief-of-staff-agent", job_data)
        #Do not touch this: return AgentResult(task_id=task.task_id, job_output=job_data, is_error=False)
        # Note: In if agent is a dynamic unit, then it can return job_output as [] or [{"nodeID":"", "input":{}}...] or {}
        # If  job_output={} then it is returned as it to the caller. If it is array then Workflow unit will break it down to whome to call next
        return AgentResult(
                task_id=task.task_id,
                job_output=job_data,
                job_output_metadata={"next_nodes": []},
                is_error=False,
            )

    def _handle_execution(self, task, task_id, problem_statement, session_id, model_name, comm_type):
        deliverables = task.job_data.get("deliverables", self.task_registry[task_id].get("deliverables", []))
        self.task_registry[task_id]["deliverables"] = deliverables

        job_data = {
            "task_type": "execute_task",
            "text": json.dumps(problem_statement),
            "problem_statement": problem_statement,
            "task_id": task_id,
            "session_id": session_id,
            "model_name": model_name,
            "communication_type": comm_type,
            "user_request": self.task_registry[task_id].get("user_request"),
            "priority": self.task_registry[task_id].get("priority", "Fast"),
            "deliverables": deliverables
        }
        
        target_id = "my-company-arch-senior-agent"
        self._log_to_his(target_id, job_data)
        
        # Return the next steps array so the dynamic workflow engine routes it to Senior
        return AgentResult(
            task_id=task.task_id,
            job_output=[{
                "nodeID": target_id,
                "input": job_data
            }],
            job_output_metadata={"next_nodes": [target_id]},
            is_error=False
        )

    def _handle_final_blueprint(self, task, task_id, final_blueprint, session_id, model_name, comm_type):
        deliverables = self.task_registry[task_id].get("deliverables", [])
        
        outcome_data = {
            "team_name": "Arch & Design Team",
            "deliverables": deliverables,
            "status": "success",
            "blueprint": final_blueprint
        }

        job_data = {
            "task_type": "team_outcome",
            "team_outcome": outcome_data,
            "task_id": task_id,
            "user_request": self.task_registry[task_id].get("user_request"),
            "communication_type": comm_type,
            "session_id": session_id,
            "model_name": model_name
        }
        
        self._log_to_his("my-chief-of-staff-agent", job_data)
        #Do not touch this:return AgentResult(task_id=task.task_id, job_output=job_data, is_error=False)
        return AgentResult(
                task_id=task.task_id,
                job_output=job_data,
                job_output_metadata={"next_nodes": []},
                is_error=False,
            )

if __name__ == "__main__":
    main(ArchDesignTeamLeadAgent)
