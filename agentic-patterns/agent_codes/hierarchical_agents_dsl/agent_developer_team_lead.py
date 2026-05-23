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

class DevEstimationSignature(dspy.Signature):
    """
    ### ROLE
    You are the Developer Team Lead.

    ### TASK
    Estimate the budget and effort for frontend and backend development.
    
    ### OUTPUT
    Output EXACTLY a JSON block: {team_name, amount, deliverables}
    """
    problem_statement = dspy.InputField(desc="The product idea")
    budget_estimate = dspy.OutputField(desc="JSON matching BudgetEstimate schema")

class DevExecutionSignature(dspy.Signature):
    """
    ### ROLE
    You are the Developer Team Lead.

    ### TASK
    Consolidate frontend and backend implementation outputs into a final delivery.
    Ensure you heavily mention and include the exact MinIO code file URLs from the reports in your final repo summary.
    
    ### OUTPUT
    Output EXACTLY a JSON block: {"team_name": "string", "deliverables": ["string"], "status": "string", "repo_summary": "string"}
    """
    problem_statement = dspy.InputField(desc="The product idea")
    architecture = dspy.InputField(desc="The system blueprint")
    dev_reports = dspy.InputField(desc="Reports from frontend and backend devs containing code file URLs")
    team_outcome = dspy.OutputField(desc="JSON matching TeamOutcome schema")

class DevTaskBreakdownSignature(dspy.Signature):
    """
    ### ROLE
    You are the Senior Technical Developer Team Lead.

    ### TASK
    Analyze the system architecture blueprint and the user request. Break down the system into highly detailed, step-by-step technical specifications for your frontend and backend engineers.
    Your instructions MUST be extraordinarily detailed:
    - Backend: Specify exact API endpoints, precise database schemas/models, authentication workflows (e.g. JWT/OAuth), and expected JSON payload structures.
    - Frontend: Specify the exact React component hierarchy, state management stores (Redux/Context), UI/UX layout instructions, and exact Axios API integration patterns.
    - Integration: Heavily emphasize how the frontend must cleanly consume the backend specifications.
    
    ### OUTPUT
    Output EXACTLY a valid JSON block mapping the comprehensive backend pointers and frontend pointers. All keys MUST be double-quoted.
    """
    problem_statement = dspy.InputField(desc="The product idea")
    architecture = dspy.InputField(desc="The system blueprint")
    dev_pointers = dspy.OutputField(desc='""Valid JSON block: {"backend_pointers": "Extensive detailed string...", "frontend_pointers": "Extensive detailed string..."}""')

# --- 2. The Developer Team Lead Agent ---

class DeveloperTeamLeadAgent:
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
                "metadata.subject_search_tags": "dev-subordinates"
            })
            self.subordinates = [agent.id for agent in known_agents.list_all()]
            log.info("Developer discovered subordinates: %s", self.subordinates)
        except Exception as e:
            log.error(f"Failed to discover developer subordinates: {e}")
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

    def _init_task(self, task_id, user_request=None, priority="Fast"):
        if task_id not in self.task_registry:
            self.task_registry[task_id] = {
                "user_request": user_request,
                "architecture": None,
                "deliverables": None,
                "backend_pointers": None,
                "frontend_pointers": None,
                "specialist_reports": {}
            }
        else:
            if user_request:
                self.task_registry[task_id]["user_request"] = user_request
            if priority:
                self.task_registry[task_id]["priority"] = priority

    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        log.info(f"Preprocessing task {task.task_id} {task.job_data}")
        text = task.job_data.get("text")
        if not text:
            # Check for allowed payload keys that indicate valid incoming tasks
            if any(k in task.job_data for k in ["problem_statement", "artifact_data", "specialist_report"]):
                return [task]
            log.warning("Task %s has no 'text' in job_data, skipping.", task.task_id)
            return None
        return [task]
    def _log_to_his(self, target_id, job_data):
        try:
            msg = {"text": str(job_data), "source_id": self.subject.identity.subject_id, "destination_id": target_id, "team": "Developer Team"}
            self.his_client.submit(input_data=msg)
        except Exception:
            pass


    def get_muxer(self):
        return None

    def on_data(self, task: AgentTask) -> AgentResult:
        try:
            data = task.job_data
            task_type = data.get("task_type", "estimate_budget")
            
            task_id = data.get("task_id", task.task_id)
            user_request = data.get("user_request")
            priority = data.get("priority", "Fast")
            self._init_task(task_id, user_request, priority)

            llm_session_id = str(uuid.uuid4())
            model_name = data.get("model_name", "aios:qwen3-1-7b-vllm-block")
            communication_type = data.get("communication_type", "delegate")
            
            # Extract problem_statement and artifact_data from text
            text = data.get("text")
            extracted = extract_json(text) if text else None
            
            problem_statement = data.get("problem_statement")
            if not problem_statement:
                problem_statement = extracted if isinstance(extracted, dict) else text
            
            if task_type == "process_artifact" and not data.get("artifact_data") and isinstance(extracted, dict):
                data["artifact_data"] = extracted

            if task_type == "process_artifact":
                src = data.get("artifact_data", {}).get("team_name", "")
                if "Arch" not in src and "Senior" not in src:
                    log.info(f"Dev Team Lead ignoring unrelated artifact from {src}")
                    return AgentResult(task_id=task.task_id, skip=True)
                    
                log.info("Dev Team Lead received recognized architecture artifact for %s", task_id)
                self.task_registry[task_id]["architecture"] = data.get("artifact_data")
                self._check_and_trigger_dev(task, task_id, problem_statement, llm_session_id, model_name, communication_type)
                return AgentResult(task_id=task.task_id, skip=True)

            elif task_type == "estimate_budget":
                return self._handle_estimation(task, task_id, problem_statement, llm_session_id, model_name, communication_type)
            
            elif task_type == "execute_task":
                # Cache deliverables but DO NOT execute yet.
                self.task_registry[task_id]["deliverables"] = data.get("deliverables", [])
                log.info("Dev Team Lead cached execution parameters for %s. Awaiting Architecture.", task_id)
                self._check_and_trigger_dev(task, task_id, problem_statement, llm_session_id, model_name, communication_type)
                return AgentResult(task_id=task.task_id, skip=True)
                
            elif task_type == "specialist_report":
                # Received dev results from frontend/backend subordinates
                agent_role = data.get("role", "Unknown Dev")
                self.task_registry[task_id]["specialist_reports"][agent_role] = data.get("specialist_report")
                log.info(f"Dev Team Lead received {agent_role} report. Total: {len(self.task_registry[task_id]['specialist_reports'])}")
                
                # If we have both Frontend and Backend, finalize the task.
                if len(self.task_registry[task_id]["specialist_reports"]) >= len(self.subordinates) and len(self.subordinates) > 0:
                    return self._finalize_execution(task, task_id, problem_statement, llm_session_id, model_name, communication_type)

            return AgentResult(task_id=task.task_id, skip=True)

        except Exception as e:
            log.exception(f"Error in Developer Team Lead: {e}")
            return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})

    def _handle_estimation(self, task, task_id, problem_statement, session_id, model_name, comm_type):
        with self._get_lm_context(model_name, session_id):
            module = dspy.ChainOfThought(DevEstimationSignature)
            result = module(problem_statement=json.dumps(problem_statement))
            
            be_raw = result.budget_estimate
            be_data = extract_json(be_raw)
            
        self._send_to_cos(task, task_id, {"budget_estimate": be_data}, session_id, comm_type)
        return AgentResult(task_id=task_id, skip=True)

    def _check_and_trigger_dev(self, task, task_id, problem_statement, session_id, model_name, comm_type):
        registry = self.task_registry[task_id]
        if registry.get("deliverables") is not None and registry.get("architecture") is not None:
            if not registry.get("backend_pointers") and not registry.get("frontend_pointers"):
                log.info("Dev Team Lead breaking down architecture into API pointers...")
                with self._get_lm_context(model_name, session_id):
                    module = dspy.ChainOfThought(DevTaskBreakdownSignature)
                    res = module(
                        problem_statement=json.dumps(problem_statement),
                        architecture=json.dumps(registry.get("architecture"))
                    )
                    pointers_data = extract_json(res.dev_pointers)
                    registry["backend_pointers"] = pointers_data.get("backend_pointers", "")
                    registry["frontend_pointers"] = pointers_data.get("frontend_pointers", "")
                    log.info("Dev Pointers Generated for Backend and Frontend.")

            log.info("Dev Team Lead has both deliverables and architecture for %s. Triggering subordinates...", task_id)
            for sub_id in self.subordinates:
                specific_pointers = registry["backend_pointers"] if "backend" in sub_id.lower() else registry["frontend_pointers"]
                
                job_data = {
                    "task_type": "execute_task",
                    "text": json.dumps(problem_statement),
                    "problem_statement": problem_statement,
                    "deliverables": registry["deliverables"],
                    "architecture": registry["architecture"],
                    "dev_pointers": specific_pointers,
                    "session_id": session_id,
                    "model_name": model_name,
                    "communication_type": comm_type,
                    "task_id": task_id,
                    "user_request": registry["user_request"]
                }
                if comm_type == "delegate":
                    self._log_to_his(sub_id, job_data)
                    self.context.delegator.submit(subject_id=sub_id, session_id=session_id, task_id=task_id, task_data=job_data)
                else:
                    self._log_to_his(sub_id, job_data)
                    self.context.p2p_manager.send_sync(task=task, subject_id=sub_id, job_data=job_data, session_id=session_id)

    def _finalize_execution(self, task, task_id, problem_statement, session_id, model_name, comm_type):
        architecture = self.task_registry[task_id].get("architecture")
        reports = self.task_registry[task_id].get("specialist_reports", {})
        
        with self._get_lm_context(model_name, session_id):
            module = dspy.ChainOfThought(DevExecutionSignature)
            result = module(
                problem_statement=json.dumps(problem_statement),
                architecture=json.dumps(architecture),
                dev_reports=json.dumps(reports)
            )
            
            outcome_raw = result.team_outcome
            outcome_data = extract_json(outcome_raw)
            
        # Programmatically inject the raw specialist repo summaries
        outcome_data["detailed_dev_reports"] = reports
        # Safely enforce team name to prevent LLM confusion from breaking the routing loop
        outcome_data["team_name"] = "Developer Team Lead"

        self._send_to_cos(task, task_id, {"team_outcome": outcome_data}, session_id, comm_type)
        return AgentResult(task_id=task_id, skip=True)

    def _send_to_cos(self, task, task_id, job_data, session_id, comm_type):
        target_id = "company-chief-of-staff-agent"
        job_data.update({
            "task_id": task_id,
            "user_request": self.task_registry[task_id].get("user_request"),
            "communication_type": comm_type
        })
        if comm_type == "delegate":
            self._log_to_his(target_id, job_data)
            self.context.delegator.submit_and_wait(subject_id=target_id, session_id=session_id, task_id=task_id, task_data=job_data)
        else:
            self._log_to_his(target_id, job_data)
            self.context.p2p_manager.send_sync(task=task, subject_id=target_id, job_data=job_data, session_id=session_id)

if __name__ == "__main__":
    main(DeveloperTeamLeadAgent)
