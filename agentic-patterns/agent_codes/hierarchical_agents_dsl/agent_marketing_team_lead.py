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

class MarketingEstimationSignature(dspy.Signature):
    """
    ### ROLE
    You are the Marketing Team Lead.

    ### TASK
    Estimate the budget and effort for marketing the product idea.
    
    ### OUTPUT
    Output EXACTLY a JSON block: {team_name, amount, deliverables}
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

# --- 2. The Marketing Team Lead Agent ---

class MarketingTeamLeadAgent:
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
                "metadata.subject_search_tags": "marketing-subordinates"
            })
            self.subordinates = [agent.id for agent in known_agents.list_all()]
            log.info("Marketing discovered subordinates: %s", self.subordinates)
        except Exception as e:
            log.error(f"Failed to discover marketing subordinates: {e}")
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
        if not text:
            # Check for report or outcome keys
            if any(key in task.job_data for key in ["specialist_report", "team_outcome"]):
                return [task]
            log.warning("Task %s has no 'text' in job_data, skipping.", task.task_id)
            return None
        return [task]
    def _log_to_his(self, target_id, job_data):
        try:
            msg = {"text": str(job_data), "source_id": self.subject.identity.subject_id, "destination_id": target_id, "team": "Marketing Team"}
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
                self.task_registry[task_id] = {
                    "user_request": user_request,
                    "priority": priority,
                    "collected_reports": {}
                }
            # else:
            #     if user_request:
            #         self.task_registry[task_id]["user_request"] = user_request

            # Extract problem_statement from text (sent from CoS)
            text = data.get("text")
            extracted = extract_json(text) if text else None
            problem_statement = extracted if isinstance(extracted, dict) else (text or data.get("problem_statement"))

            if task_type == "estimate_budget":
                return self._handle_estimation(task, task_id, problem_statement, llm_session_id, model_name, communication_type)
            
            elif task_type == "execute_task":
                return self._handle_execution(task, task_id, problem_statement, llm_session_id, model_name, communication_type)

            elif task_type == "specialist_report":
                report = data.get("specialist_report")
                if report:
                    spec_id = report.get('team_name', 'unknown_specialist')
                    self.task_registry[task_id]["collected_reports"][spec_id] = report
                    log.info(f"Marketing Lead collected report from {spec_id}. Total: {len(self.task_registry[task_id]['collected_reports'])}")
                    
                    # We have 4 specialists
                    if len(self.task_registry[task_id]["collected_reports"]) >= 4:
                        return self._finalize_execution(task, task_id, problem_statement, llm_session_id, model_name, communication_type)
                
            return AgentResult(task_id=task.task_id, skip=True)

        except Exception as e:
            log.exception(f"Error in Marketing Team Lead: {e}")
            return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})

    def _handle_estimation(self, task, task_id, problem_statement, session_id, model_name, comm_type):
        with self._get_lm_context(model_name, session_id):
            module = dspy.ChainOfThought(MarketingEstimationSignature)
            result = module(problem_statement=json.dumps(problem_statement))
            
            be_raw = result.budget_estimate
            estimate_data = extract_json(be_raw)
            
        job_data = {
            "budget_estimate": estimate_data,
            "task_id": task_id,
            "user_request": self.task_registry[task_id].get("user_request"),
            "communication_type": comm_type
        }
        self._send_to_cos(task, job_data, session_id, comm_type)
        return AgentResult(task_id=task.task_id, skip=True)

    def _handle_execution(self, task, task_id, problem_statement, session_id, model_name, comm_type):
        log.info(f"Marketing Team Lead distributing execution task {task_id} to {len(self.subordinates)} specialists.")
        
        job_data = {
            "task_type": "execute_task",
            "problem_statement": problem_statement,
            "task_id": task_id,
            "session_id": session_id,
            "model_name": model_name,
            "communication_type": comm_type,
            "user_request": self.task_registry[task_id].get("user_request")
        }
        
        for sub_id in self.subordinates:
            if comm_type == "delegate":
                self._log_to_his(sub_id, job_data)
                self.context.delegator.submit(subject_id=sub_id, session_id=session_id, task_id=task_id, task_data=job_data)
            else:
                self._log_to_his(sub_id, job_data)
                self.context.p2p_manager.send_sync(task=task, subject_id=sub_id, job_data=job_data, session_id=session_id)
                
        return AgentResult(task_id=task.task_id, skip=True)

    def _finalize_execution(self, task, task_id, problem_statement, session_id, model_name, comm_type):
        reports = self.task_registry[task_id].get("collected_reports", {})
        reports_json = json.dumps(reports, indent=2)
        
        with self._get_lm_context(model_name, session_id):
            module = dspy.ChainOfThought(MarketingExecutionSignature)
            result = module(problem_statement=json.dumps(problem_statement), specialist_reports=reports_json)
            
            outcome_raw = result.team_outcome
            outcome_data = extract_json(outcome_raw)
            
        # Programmatically inject the raw specialist reports to prevent LLM truncation
        outcome_data["specialist_detailed_reports"] = reports
        outcome_data["team_name"] = "Marketing Team Lead"

        job_data = {
            "team_outcome": outcome_data,
            "task_id": task_id,
            "user_request": self.task_registry[task_id].get("user_request"),
            "communication_type": comm_type
        }
        self._send_to_cos(task, job_data, session_id, comm_type)
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
    main(MarketingTeamLeadAgent)
