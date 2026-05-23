import logging
import uuid
import json
import dspy
from typing import Any, Dict, List, Optional

from agents_sdk.core.agent_executor import AgentResult, AgentTask, Context
from agents_sdk.core.main import main
from agents_sdk.core.his import HisClient
from agents_sdk.core.known_agents import KnownAgents
from utils.dspy_aios_llms import AIOS_DSPy_LMs
from utils.hierarchical_agents_models import BudgetEstimate, TeamOutcome
from utils.json_utils import extract_json

log = logging.getLogger(__name__)

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

# --- 2. The Arch & Design Team Lead Agent ---

class ArchDesignTeamLeadAgent:
    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        self.persona_default_system_message = self.subject.persona.default_system_message
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        self.task_registry = {}

        # Dynamic Discovery
        try:
            known_agents = KnownAgents(default_compact=False)
            known_agents.query_and_add(query={
                "metadata.subject_search_tags": "arch-subordinates"
            })
            self.subordinates = [agent.id for agent in known_agents.list_all()]
            log.info("Architecture discovered subordinates: %s", self.subordinates)
        except Exception as e:
            log.error(f"Failed to discover architecture subordinates: {e}")
            self.subordinates = []
        # Initialize HIS Client
        his_config = self.subject.persona.config.get("parameters", {}).get("HIS_CONFIG", {})
        self.his_client = HisClient(
            base_url=his_config["HIS_BASE_URL"],
            poll_interval=his_config.get("HIS_POLL_INTERVAL", 1.0),
            max_wait=his_config.get("HIS_MAX_WAIT", 60)
        )


    def _get_lm_context(self, model_name, session_id):
        return dspy.settings.context(lm=self.aios_dspy_lm.get_choosen_model(model_name=model_name, session_id=session_id))


    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        log.info(f"Preprocessing task {task.task_id} {task.job_data}")
        text = task.job_data.get("text")
        if not text and "final_blueprint" not in task.job_data:
            log.warning("Task %s has no 'text' or 'final_blueprint' in job_data, skipping.", task.task_id)
            return None
        return [task]
    def _log_to_his(self, target_id, job_data):
        try:
            msg = {"text": str(job_data), "source_id": self.subject.identity.subject_id, "destination_id": target_id, "team": "Architecture Team"}
            self.his_client.submit(input_data=msg)
        except Exception:
            pass


    def get_muxer(self):
        return None

    def on_data(self, task: AgentTask) -> AgentResult:
        try:
            data = task.job_data
            task_type = data.get("task_type", "estimate_budget")
            llm_session_id = str(uuid.uuid4())
            model_name = data.get("model_name", "aios:qwen3-1-7b-vllm-block")
            communication_type = data.get("communication_type", "delegate")
            
            task_id = data.get("task_id", task.task_id)
            user_request = data.get("user_request")
            
            priority = data.get("priority", "Fast")
            if task_id not in self.task_registry:
                self.task_registry[task_id] = {"user_request": user_request, "priority": priority}
            else:
                if user_request:
                    self.task_registry[task_id]["user_request"] = user_request
                if "priority" in data:
                    self.task_registry[task_id]["priority"] = priority

            # Extract problem_statement from text (sent from CoS)
            text = data.get("text")
            extracted = extract_json(text) if text else None
            problem_statement = extracted if isinstance(extracted, dict) else (text or data.get("problem_statement"))

            if task_type == "estimate_budget":
                return self._handle_estimation(task, task_id, problem_statement, llm_session_id, model_name, communication_type)
            
            elif task_type == "execute_task":
                return self._handle_execution(task, task_id, problem_statement, llm_session_id, model_name, communication_type)

            elif task_type == "final_blueprint":
                # Senior sends this back when debate is finished
                return self._handle_final_blueprint(task, task_id, data, llm_session_id, model_name, communication_type)

            return AgentResult(task_id=task.task_id, skip=True)

        except Exception as e:
            log.exception(f"Error in Arch Team Lead: {e}")
            return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})

    def _handle_estimation(self, task, task_id, problem_statement, session_id, model_name, comm_type):
        with self._get_lm_context(model_name, session_id):
            module = dspy.ChainOfThought(ArchEstimationSignature)
            result = module(problem_statement=json.dumps(problem_statement))
            
            be_raw = result.budget_estimate
            be_data = extract_json(be_raw)
            
        job_data = {
            "budget_estimate": be_data,
            "task_id": task_id,
            "user_request": self.task_registry[task_id].get("user_request"),
            "communication_type": comm_type
        }
        
        # Globally store deliverables for execution phase
        self.task_registry[task_id]["deliverables"] = be_data.get("deliverables", [])
        
        self._send_to_cos(task, job_data, session_id, comm_type)
        return AgentResult(task_id=task.task_id, skip=True)

    def _handle_execution(self, task, task_id, problem_statement, session_id, model_name, comm_type):
        deliverables = task.job_data.get("deliverables", self.task_registry[task_id].get("deliverables", []))
        self.task_registry[task_id]["deliverables"] = deliverables

        job_data = {
            "task_type": "initial_design",
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
        
        target_id = "company-arch-junior-agent"
        if comm_type == "delegate":
            self._log_to_his(target_id, job_data)
            self.context.delegator.submit_and_wait(subject_id=target_id, session_id=session_id, task_id=task.task_id, task_data=job_data)
        else:
            self._log_to_his(target_id, job_data)
            self.context.p2p_manager.send_sync(task=task, subject_id=target_id, job_data=job_data, session_id=session_id)
            
        return AgentResult(task_id=task.task_id, skip=True)

    def _handle_final_blueprint(self, task, task_id, data, session_id, model_name, comm_type):
        deliverables = self.task_registry[task_id].get("deliverables", [])
        
        outcome_data = {
            "team_name": "Arch & Design Team",
            "deliverables": deliverables,
            "status": "success",
            "blueprint": data.get("final_blueprint", "Blueprint missing")
        }

        job_data = {
            "team_outcome": outcome_data,
            "task_id": task_id,
            "user_request": self.task_registry[task_id].get("user_request"),
            "communication_type": comm_type
        }
        
        # Broadcast to CoS
        self._send_to_cos(task, job_data, session_id, comm_type)
        
        # Broadcast to Dev and Testing Team Leads (P2P only)
        # targets = ["company-developer-team-lead", "company-testing-team-lead"]
        
        # artifact_data = {
        #     "task_type": "process_artifact",
        #     "artifact_data": outcome_data,
        #     "text": json.dumps(outcome_data),
        #     "task_id": task_id,
        #     "session_id": session_id,
        #     "model_name": model_name,
        #     "communication_type": "p2p",
        #     "user_request": self.task_registry[task_id].get("user_request"),
        #     "priority": self.task_registry[task_id].get("priority", "Fast")
        # }
        
        # for target_id in targets:
        #     self._log_to_his(target_id, artifact_data)     self.context.p2p_manager.send_sync(task=task, subject_id=target_id, job_data=artifact_data, session_id=session_id)

        return AgentResult(task_id=task.task_id, skip=True)

    def _send_to_cos(self, parent_task, job_data, session_id, comm_type):
        target_id = "company-chief-of-staff-agent"
        if comm_type == "delegate":
            self._log_to_his(target_id, job_data)
            self.context.delegator.submit_and_wait(subject_id=target_id, session_id=session_id, task_id=parent_task.task_id, task_data=job_data)
        else:
            self._log_to_his(target_id, job_data)
            self.context.p2p_manager.send_sync(task=parent_task, subject_id=target_id, job_data=job_data, session_id=session_id)

if __name__ == "__main__":
    main(ArchDesignTeamLeadAgent)
