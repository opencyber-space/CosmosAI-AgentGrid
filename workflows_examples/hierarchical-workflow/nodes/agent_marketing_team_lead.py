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
from utils.json_utils import extract_json

log = logging.getLogger(__name__)

NODE_ID_MAPPING = {
    "agent-workflow-marketing-team-lead": "my-company-marketing-team-lead-agent",
    "agent-workflow-marketing-content": "my-company-marketing-content-agent",
    "agent-workflow-marketing-planning": "my-company-marketing-planning-agent",
    "agent-workflow-marketing-strategy": "my-company-marketing-strategy-agent",
    "agent-workflow-marketing-visual": "my-company-marketing-visual-agent",
    "agent-workflow-cos":"my-chief-of-staff-agent"
}

NODE_TEAM_LEAD = "my-company-marketing-team-lead-agent"
NODE_MARKETING_CONTENT = "my-company-marketing-content-agent"
NODE_MARKETING_PLANNING = "my-company-marketing-planning-agent"
NODE_MARKETING_STRATEGY = "my-company-marketing-strategy-agent"
NODE_MARKETING_VISUAL = "my-company-marketing-visual-agent"
NODE_COS = "my-chief-of-staff-agent"

class MarketingEstimationSignature(dspy.Signature):
    """
    ### ROLE
    You are the Marketing Team Lead.

    ### TASK
    Estimate the budget and effort for marketing the product idea.
    
    ### OUTPUT
    Output EXACTLY a JSON block: {team_name, amount, deliverables}
    CRITICAL: The 'amount' field MUST be a single integer representing the total cost. DO NOT output 'amount' as a string (like "$18,000") or a dictionary.
    """
    problem_statement = dspy.InputField(desc="The product idea")
    budget_estimate = dspy.OutputField(desc="JSON matching BudgetEstimate schema")

class MarketingExecutionSignature(dspy.Signature):
    """
    ### ROLE
    You are the Marketing Team Lead.

    ### TASK
    Synthesize the marketing strategy and deliverables based on the specialists' outputs and the problem statement.
    
    ### OUTPUT
    Output EXACTLY a JSON block: {team_name, deliverables: List[str], status: str}
    """
    problem_statement = dspy.InputField(desc="The product idea")
    specialist_reports = dspy.InputField(desc="Dictionary mapping specialist names to their generated outputs")
    team_outcome = dspy.OutputField(desc="JSON matching TeamOutcome schema")

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

class MarketingTeamLeadAgent:
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
        if "initial_input" in data and isinstance(data["initial_input"], dict):
            data = data["initial_input"]
            
        text = data.get("text")
        if not text and not any(key in data for key in ["specialist_report", "team_outcome", "problem_statement"]):
            log.warning("Task %s has no 'text' or actionable keys in job_data, skipping.", task.task_id)
            return None
        return [task]

    def _log_to_his(self, target_id, job_data):
        try:
            source_id = getattr(self.subject.identity, 'subject_id', 'unknown')
            target_id_mapped = {v: k for k, v in NODE_ID_MAPPING.items()}.get(target_id, target_id)
            msg = {"text": str(job_data), "source_id": source_id, "destination_id": target_id_mapped, "team": "Marketing Team", "timestamp": time.time()}
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
                log.info("Unpacking dynamic router payload in Marketing Lead")
                data = data.get("initial_input", {})
                
            task_id = data.get("task_id", task.task_id)
            user_request = data.get("user_request")
            priority = data.get("priority", "Fast")
            task_type = data.get("task_type", "approve_budget")

            history      = task.job_data.get("history", [])
            outputs      = task.job_data.get("outputs", {})
            initial_input = task.job_data.get("initial_input", {})
            last_executed = task.job_data.get("last_executed")
            # Note: use last_executed_batch when task is executed in parallel from this agent
            last_executed_batch = task.job_data.get("last_executed_batch")
            final_blueprint = ""
            last_node = None
            last_nodes = None
            if len(last_executed_batch)>1:
                # Note: use last_executed_batch when task is executed in parallel from this agent
                task_type = last_executed["output"]["task_type"]
                last_nodes = [node["nodeID"] for node in last_executed_batch]
            elif last_executed and "output" in last_executed:
                if "final_blueprint" in last_executed["output"]:
                    final_blueprint = last_executed["output"]["final_blueprint"]
                #elif last_executed["output"]["task_type"] == "specialist_output":
                last_node = last_executed["nodeID"]
                task_type = last_executed["output"]["task_type"]
            
            raw_text, communication_type, model_name, session_id = self.payload_processor.prepare_payload(task)

            if task_id not in self.task_registry:
                self.task_registry[task_id] = {
                    "user_request": user_request,
                    "priority": priority,
                    "collected_reports": {}
                }

            text = data.get("text")
            extracted = extract_json(text) if text else None
            problem_statement = extracted if isinstance(extracted, dict) else (text or data.get("problem_statement") or raw_text)

            llm_session_id = data.get("session_id", str(uuid.uuid4()))

            if task_type == "estimate_budget":
                return self._handle_estimation(task, task_id, problem_statement, llm_session_id, model_name, communication_type)
            
            elif task_type == "execute_task":
                return self._handle_execution(task, task_id, problem_statement, llm_session_id, model_name, communication_type)

            elif task_type == "specialist_report":
                for i, one_last_node in enumerate(last_nodes):
                    team_name = last_executed_batch[i]["output"]["specialist_report"]["team_name"]
                    if "collected_reports" not in self.task_registry[task_id]:
                        self.task_registry[task_id]["collected_reports"] = {}

                    self.task_registry[task_id]["collected_reports"][team_name] = last_executed_batch[i]["output"]["specialist_report"]
                    log.info(f"Marketing Lead collected report from {team_name}. Total: {len(self.task_registry[task_id]['collected_reports'])}")
                    
                    if len(self.task_registry[task_id]["collected_reports"]) >= 4:
                        return self._finalize_execution(task, task_id, problem_statement, llm_session_id, model_name, communication_type)
                
            return AgentResult(task_id=task.task_id, skip=True)

        except Exception as e:
            log.exception(f"Error in Marketing Team Lead: {e}")
            return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})

    def _handle_estimation(self, task, task_id, problem_statement, session_id, model_name, comm_type):
        with self.model_context.get_context(model_name=model_name, session_id=session_id):
            module = dspy.ChainOfThought(MarketingEstimationSignature)
            result = module(problem_statement=json.dumps(problem_statement))
            
            be_raw = result.budget_estimate
            estimate_data = extract_json(be_raw)
            
        job_data = {
            "task_type": "budget_estimate",
            "budget_estimate": estimate_data,
            "task_id": task_id,
            "user_request": self.task_registry[task_id].get("user_request"),
            "communication_type": comm_type,
            "session_id": session_id,
            "model_name": model_name
        }
        self._log_to_his(NODE_COS, job_data)
        #return AgentResult(task_id=task.task_id, job_output=job_data, is_error=False)
        # Note: In if agent is a dynamic unit, then it can return job_output as [] or [{"nodeID":"", "input":{}}...] or {}
        # If  job_output={} then it is returned as it to the caller. If it is array then Workflow unit will break it down to whome to call next
        return AgentResult(
                task_id=task.task_id,
                job_output=job_data,
                job_output_metadata={"next_nodes": []},
                is_error=False,
            )

    def _handle_execution(self, task, task_id, problem_statement, session_id, model_name, comm_type):
        log.info(f"Marketing Team Lead distributing execution task {task_id} to 4 specialists.")
        
        job_data = {
            "task_type": "execute_task",
            "problem_statement": problem_statement,
            "task_id": task_id,
            "session_id": session_id,
            "model_name": model_name,
            "communication_type": comm_type,
            "user_request": self.task_registry[task_id].get("user_request")
        }
        
        for sub_id in [NODE_MARKETING_CONTENT, NODE_MARKETING_PLANNING, NODE_MARKETING_STRATEGY, NODE_MARKETING_VISUAL]:
            self._log_to_his(sub_id, job_data)
        input_to_next_agents = [{"nodeID":NODE_MARKETING_CONTENT, "input":job_data},
                                {"nodeID":NODE_MARKETING_PLANNING, "input":job_data},
                                {"nodeID":NODE_MARKETING_STRATEGY, "input":job_data},
                                {"nodeID":NODE_MARKETING_VISUAL, "input":job_data}]
        return AgentResult(task_id=task.task_id, 
                            job_output=input_to_next_agents, 
                            job_output_metadata={"next_nodes": [NODE_MARKETING_CONTENT, NODE_MARKETING_PLANNING, NODE_MARKETING_STRATEGY, NODE_MARKETING_VISUAL]}, 
                            is_error=False)

    def _finalize_execution(self, task, task_id, problem_statement, session_id, model_name, comm_type):
        reports = self.task_registry[task_id].get("collected_reports", {})
        reports_json = json.dumps(reports, indent=2)
        
        with self.model_context.get_context(model_name=model_name, session_id=session_id):
            module = dspy.ChainOfThought(MarketingExecutionSignature)
            result = module(problem_statement=json.dumps(problem_statement), specialist_reports=reports_json)
            
            outcome_raw = result.team_outcome
            outcome_data = extract_json(outcome_raw)
            
        outcome_data["specialist_detailed_reports"] = reports
        outcome_data["team_name"] = "Marketing Team Lead"

        job_data = {
            "task_type": "team_outcome",
            "team_outcome": outcome_data,
            "task_id": task_id,
            "user_request": self.task_registry[task_id].get("user_request"),
            "communication_type": comm_type,
            "session_id": session_id,
            "model_name": model_name
        }
        self._log_to_his(NODE_COS, job_data)
        return AgentResult(task_id=task.task_id, job_output=job_data,job_output_metadata={"next_nodes": []}, is_error=False)

if __name__ == "__main__":
    main(MarketingTeamLeadAgent)
