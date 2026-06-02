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
    "agent-workflow-developer-team-lead": "my-company-developer-team-lead-agent",
    "agent-workflow-dev-backend": "my-company-dev-backend-agent",
    "agent-workflow-dev-frontend": "my-company-dev-frontend-agent",
    "agent-workflow-cos":"my-chief-of-staff-agent"
}

NODE_BACKEND = "my-company-dev-backend-agent"
NODE_FRONTEND = "my-company-dev-frontend-agent"
NODE_COS = "my-chief-of-staff-agent"

# --- 1. The Signatures ---

class DevEstimationSignature(dspy.Signature):
    """
    ### ROLE
    You are the Developer Team Lead.

    ### TASK
    Estimate the budget and effort for frontend and backend development.
    
    ### OUTPUT
    Output EXACTLY a JSON block: {team_name, amount, deliverables}
    CRITICAL: The 'amount' field MUST be a single integer representing the total cost. DO NOT output 'amount' as a dictionary with currency and value.
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
    Analyze the system architecture blueprint and the user request. Break down the system into high-level technical specifications for your frontend and backend engineers.
    Your instructions MUST be extremely concise and action-oriented:
    - Backend: Key API endpoints, core database models, and critical auth workflows.
    - Frontend: Core React component hierarchy, state management approach, and key API integration patterns.
    - CRITICAL: Keep your response as short as possible (under 1500 words) to prevent JSON truncation errors! DO NOT write exhaustive code or exhaustive schema boilerplate. Provide strictly high-level pointers.
    
    ### OUTPUT
    Output EXACTLY a valid JSON block mapping the comprehensive backend pointers and frontend pointers. All keys MUST be double-quoted.
    CRITICAL JSON PARSING RULES:
    1. DO NOT USE double quotes (") ANYWHERE inside the text content of your pointers.
    2. For any JSON payloads or code examples, you MUST use single quotes (') instead of double quotes. Example: {'email': 'string'}
    3. Escape all newlines as \\n. DO NOT use literal newlines.
    4. ENSURE the JSON is fully closed and not truncated. Keep text short!
    """
    problem_statement = dspy.InputField(desc="The product idea")
    architecture = dspy.InputField(desc="The system blueprint")
    dev_pointers = dspy.OutputField(desc='""Valid JSON block: {"backend_pointers": "Extensive detailed string...", "frontend_pointers": "Extensive detailed string..."}""')

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

# --- 2. The Developer Team Lead Agent ---

class DeveloperTeamLeadAgent:
    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        self.persona_default_system_message = getattr(self.subject.persona, 'default_system_message', "") if hasattr(self.subject, 'persona') else ""
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        
        self.payload_processor = AgentPayloadProcessor()
        self.model_context = ModelContextManager(self.aios_dspy_lm)
        self.task_registry = {}
        self.subordinates = ["Backend Developer", "Frontend Developer"]

        # Initialize HIS Client
        his_config = getattr(self.subject.persona, 'config', {}).get("parameters", {}).get("HIS_CONFIG", {}) if hasattr(self.subject, 'persona') else {}
        self.his_client = HisClient(
            base_url=his_config.get("HIS_BASE_URL", "http://localhost"),
            poll_interval=his_config.get("HIS_POLL_INTERVAL", 1.0),
            max_wait=his_config.get("HIS_MAX_WAIT", 60)
        )

    def _init_task(self, task_id, user_request=None, priority="Fast"):
        if task_id not in self.task_registry:
            self.task_registry[task_id] = {
                "user_request": user_request,
                "priority": priority,
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
        data = task.job_data
        if not isinstance(data, dict):
            data = {}
        if "initial_input" in data and isinstance(data["initial_input"], dict):
            data = data["initial_input"]
            
        text = data.get("text")
        if not text:
            # Check for allowed payload keys that indicate valid incoming tasks
            if any(k in data for k in ["problem_statement", "artifact_data", "specialist_report"]):
                return [task]
            log.warning("Task %s has no 'text' in job_data, skipping.", task.task_id)
            return None
        return [task]

    def _log_to_his(self, target_id, job_data):
        try:
            source_id = getattr(self.subject.identity, 'subject_id', 'unknown')
            target_id_mapped = {v: k for k, v in NODE_ID_MAPPING.items()}.get(target_id, target_id)
            msg = {"text": str(job_data), "source_id": source_id, "destination_id": target_id_mapped, "team": "Developer Team", "timestamp": time.time()}
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
                log.info("Unpacking dynamic router payload in Developer Lead")
                data = data.get("initial_input", {})
                
            task_type = data.get("task_type", "estimate_budget")

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
            
            task_id = data.get("task_id", task.task_id)
            user_request = data.get("user_request")
            priority = data.get("priority", "Fast")
            self._init_task(task_id, user_request, priority)
 
            raw_text, communication_type, model_name, session_id = self.payload_processor.prepare_payload(task)
            llm_session_id = data.get("session_id", str(uuid.uuid4()))
            
            # Consistent problem_statement extraction logic (Rule GEMINI.md)
            text = data.get("text")
            extracted = extract_json(text) if text else None
            
            problem_statement = data.get("problem_statement")
            if not problem_statement:
                problem_statement = extracted if isinstance(extracted, dict) else text
            
            if not problem_statement:
                problem_statement = self.task_registry[task_id].get("user_request", user_request)

            # if task_type == "process_artifact" and not data.get("artifact_data") and isinstance(extracted, dict):
            #     data["artifact_data"] = extracted

            if task_type == "process_artifact":
                log.info(f"Dev Team Lead received artifact data for {task_id}: {data.get('artifact_data')}")
                src = data.get("artifact_data", {}).get("team_name", "")
                if "Arch" not in src and "Senior" not in src:
                    log.info(f"Dev Team Lead ignoring unrelated artifact from {src}")
                    return AgentResult(task_id=task.task_id, skip=True)
                    
                log.info("Dev Team Lead received recognized architecture artifact for %s", task_id)
                self.task_registry[task_id]["architecture"] = data.get("artifact_data")
                return self._check_and_trigger_dev(task, task_id, problem_statement, llm_session_id, model_name, communication_type)

            elif task_type == "estimate_budget":
                return self._handle_estimation(task, task_id, problem_statement, llm_session_id, model_name, communication_type)
            
            elif task_type == "execute_task":
                # Cache deliverables but DO NOT execute yet.
                self.task_registry[task_id]["deliverables"] = data.get("deliverables", [])
                log.info("Dev Team Lead cached execution parameters for %s. Awaiting Architecture.", task_id)
                return self._check_and_trigger_dev(task, task_id, problem_statement, llm_session_id, model_name, communication_type)
                
            elif task_type == "specialist_report":
                # Received dev results from frontend/backend subordinates
                for i, one_last_node in enumerate(last_nodes):
                    agent_role = last_executed_batch[i]["output"]["role"]
                    if "specialist_reports" not in self.task_registry[task_id]:
                        self.task_registry[task_id]["specialist_reports"] = {}
                    self.task_registry[task_id]["specialist_reports"][agent_role] = last_executed_batch[i]["output"]["specialist_report"]
                    log.info(f"Dev Team Lead received {agent_role} report. Total: {len(self.task_registry[task_id]['specialist_reports'])}")
                
                # If we have both Frontend and Backend, finalize the task.
                if len(self.task_registry[task_id]["specialist_reports"]) >= len(self.subordinates):
                    return self._finalize_execution(task, task_id, problem_statement, llm_session_id, model_name, communication_type)

            return AgentResult(task_id=task.task_id, job_output={}, job_output_metadata={"next_nodes":[]}, is_error=False)

        except Exception as e:
            log.exception(f"Error in Developer Team Lead: {e}")
            return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})

    def _handle_estimation(self, task, task_id, problem_statement, session_id, model_name, comm_type):
        with self.model_context.get_context(model_name, session_id):
            module = dspy.ChainOfThought(DevEstimationSignature)
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

    def _check_and_trigger_dev(self, task, task_id, problem_statement, session_id, model_name, comm_type):
        registry = self.task_registry[task_id]
        if registry.get("deliverables") is not None and registry.get("architecture") is not None:
            if not registry.get("backend_pointers") and not registry.get("frontend_pointers"):
                log.info("Dev Team Lead breaking down architecture into API pointers...")
                with self.model_context.get_context(model_name, session_id):
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
            
            job_data = {
                "task_type": "execute_task",
                "text": json.dumps(problem_statement),
                "problem_statement": problem_statement,
                "deliverables": registry["deliverables"],
                "architecture": registry["architecture"],
                "backend_pointers": registry["backend_pointers"],
                "frontend_pointers": registry["frontend_pointers"],
                "session_id": session_id,
                "model_name": model_name,
                "communication_type": comm_type,
                "task_id": task_id,
                "user_request": registry["user_request"]
            }
            
            for sub_id in [NODE_BACKEND, NODE_FRONTEND]:
                self._log_to_his(sub_id, job_data)
            input_for_dev = [{"nodeID":NODE_BACKEND, "input":job_data}, {"nodeID":NODE_FRONTEND, "input":job_data}]
            return AgentResult(task_id=task.task_id, job_output=input_for_dev, job_output_metadata={"next_nodes":[NODE_BACKEND, NODE_FRONTEND]}, is_error=False)
        else:
            log.info("Dev Team Lead awaiting dependencies for %s. Deliverables: %s | Architecture: %s",
                     task_id,
                     "Cached" if registry.get("deliverables") is not None else "Missing",
                     "Cached" if registry.get("architecture") is not None else "Missing")
            return AgentResult(task_id=task.task_id, job_output={}, job_output_metadata={"next_nodes":[]}, is_error=False)

    def _finalize_execution(self, task, task_id, problem_statement, session_id, model_name, comm_type):
        architecture = self.task_registry[task_id].get("architecture")
        reports = self.task_registry[task_id].get("specialist_reports", {})
        
        with self.model_context.get_context(model_name, session_id):
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
        return AgentResult(task_id=task.task_id, job_output=job_data, job_output_metadata={"next_nodes":[]}, is_error=False)

if __name__ == "__main__":
    main(DeveloperTeamLeadAgent)
