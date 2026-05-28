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

class TestingEstimationSignature(dspy.Signature):
    """
    ### ROLE
    You are the Testing Team Lead.

    ### TASK
    Estimate the budget and effort for test planning and validation.
    IMPORTANT: The estimated amount must be purely a number (e.g., 38000), do not use text or currency symbols like '$38,000'.
    
    ### OUTPUT
    Output EXACTLY a JSON block: {team_name, amount, deliverables}
    """
    problem_statement = dspy.InputField(desc="The product idea")
    budget_estimate = dspy.OutputField(desc="JSON matching BudgetEstimate schema")

class TestingExecutionSignature(dspy.Signature):
    """
    ### ROLE
    You are the Testing Team Lead.

    ### TASK
    Execute the test plan and produce a pass/fail validation report.
    
    ### OUTPUT
    Output EXACTLY a JSON block: {team_name, deliverables: List[str], status: str, passed: bool, bugs: List[str]}
    """
    problem_statement = dspy.InputField(desc="The product idea")
    architecture = dspy.InputField(desc="The system blueprint")
    dev_output = dspy.InputField(desc="The implementation summary from development")
    team_outcome = dspy.OutputField(desc="JSON matching TeamOutcome schema")

class TestingArchAnalysisSignature(dspy.Signature):
    """
    ### ROLE
    You are the Testing Team Lead.

    ### TASK
    Analyze the system architecture blueprint and generate high-level test case scenarios that need to be covered.
    
    ### OUTPUT
    Output EXACTLY a valid JSON block containing a list of strings. All keys MUST be double-quoted.
    """
    problem_statement = dspy.InputField(desc="The product idea")
    architecture = dspy.InputField(desc="The system blueprint")
    arch_design_test_cases = dspy.OutputField(desc='""Valid JSON block: {"high_level_test_cases": ["string", "string"]}""')

class TestingModuleTestCasesSignature(dspy.Signature):
    """
    ### ROLE
    You are the Testing Team Lead.

    ### TASK
    Analyze the developer's output modules against the high-level test cases (planned during the architecture phase).
    Generate specific, granular test cases for each of the developed modules.
    
    ### OUTPUT
    Output EXACTLY a valid JSON block containing a list of strings. All keys MUST be double-quoted.
    """
    architecture = dspy.InputField(desc="The system blueprint")
    dev_output = dspy.InputField(desc="The implementation summary from development")
    arch_design_test_cases = dspy.InputField(desc="High-level test cases planned earlier")
    module_test_cases = dspy.OutputField(desc='""Valid JSON block: {"module_test_cases": ["string", "string"]}""')

# --- 2. The Testing Team Lead Agent ---

class TestingTeamLeadAgent:
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
                "metadata.subject_search_tags": "testing-subordinates"
            })
            self.subordinates = [agent.id for agent in known_agents.list_all()]
            log.info("Testing discovered subordinates: %s", self.subordinates)
        except Exception as e:
            log.error(f"Failed to discover testing subordinates: {e}")
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
                "priority": priority,
                "architecture": None,
                "dev_output": None,
                "deliverables": None,
                "arch_design_test_cases": None,
                "module_test_cases": None,
                "specialist_report": None
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
            msg = {"text": str(job_data), "source_id": self.subject.identity.subject_id, "destination_id": target_id, "team": "Testing Team"}
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
                if "Arch" in src or "Senior" in src:
                    self.task_registry[task_id]["architecture"] = data.get("artifact_data")
                    log.info("Testing Team Lead received architecture for %s. Generating High-Level Test Plan...", task_id)
                    with self._get_lm_context(model_name, llm_session_id):
                        module = dspy.ChainOfThought(TestingArchAnalysisSignature)
                        res = module(
                            problem_statement=json.dumps(problem_statement),
                            architecture=json.dumps(data.get("artifact_data"))
                        )
                        self.task_registry[task_id]["arch_design_test_cases"] = extract_json(res.arch_design_test_cases)
                        log.info(f"High-Level Test Plan Generated: {self.task_registry[task_id]['arch_design_test_cases']}")
                elif "Developer" in src or "Frontend" in src or "Backend" in src:
                    self.task_registry[task_id]["dev_output"] = data.get("artifact_data")
                    log.info("Testing Team Lead received developer output for %s.", task_id)
                
                self._check_and_trigger_testing(task, task_id, problem_statement, llm_session_id, model_name, communication_type)
                return AgentResult(task_id=task.task_id, skip=True)

            elif task_type == "estimate_budget":
                return self._handle_estimation(task, task_id, problem_statement, llm_session_id, model_name, communication_type)
            
            elif task_type == "execute_task":
                # Cache deliverables but DO NOT execute yet.
                self.task_registry[task_id]["deliverables"] = data.get("deliverables", [])
                log.info("Testing Team Lead cached execution parameters for %s. Awaiting Developer output.", task_id)
                self._check_and_trigger_testing(task, task_id, problem_statement, llm_session_id, model_name, communication_type)
                return AgentResult(task_id=task.task_id, skip=True)
                
            elif task_type == "specialist_report":
                # Received test results from agent_testing_dev.py
                self.task_registry[task_id]["specialist_report"] = data.get("specialist_report")
                log.info("Testing Team Lead received final test results for %s. Sending to CoS...", task_id)
                return self._finalize_execution(task, task_id, problem_statement, llm_session_id, model_name, communication_type)

            return AgentResult(task_id=task.task_id, skip=True)

        except Exception as e:
            log.exception(f"Error in Testing Team Lead: {e}")
            return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})

    def _handle_estimation(self, task, task_id, problem_statement, session_id, model_name, comm_type):
        with self._get_lm_context(model_name, session_id):
            module = dspy.ChainOfThought(TestingEstimationSignature)
            result = module(problem_statement=json.dumps(problem_statement))
            
            be_raw = result.budget_estimate
            be_data = extract_json(be_raw)
            
        self._send_to_cos(task, task_id, {"budget_estimate": be_data}, session_id, comm_type, model_name)
        return AgentResult(task_id=task_id, skip=True)

    def _check_and_trigger_testing(self, task, task_id, problem_statement, session_id, model_name, comm_type):
        registry = self.task_registry[task_id]
        if registry.get("deliverables") is not None and registry.get("dev_output") is not None:
            if not registry.get("module_test_cases"):
                log.info("Testing Team Lead generating module-specific test cases based on Developer Output...")
                with self._get_lm_context(model_name, session_id):
                    module = dspy.ChainOfThought(TestingModuleTestCasesSignature)
                    res = module(
                        architecture=json.dumps(registry.get("architecture")),
                        dev_output=json.dumps(registry.get("dev_output")),
                        arch_design_test_cases=json.dumps(registry.get("arch_design_test_cases", []))
                    )
                    registry["module_test_cases"] = extract_json(res.module_test_cases)
                    log.info(f"Module Test Cases Generated: {registry['module_test_cases']}")

            log.info("Testing Team Lead has both deliverables and dev_output for %s. Triggering subordinates...", task_id)
            for sub_id in self.subordinates:
                job_data = {
                    "task_type": "execute_task",
                    "text": json.dumps(problem_statement),
                    "problem_statement": problem_statement,
                    "deliverables": registry["deliverables"],
                    "dev_output": registry["dev_output"],
                    "architecture": registry["architecture"],
                    "arch_design_test_cases": registry["arch_design_test_cases"],
                    "module_test_cases": registry["module_test_cases"],
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
        dev_output = self.task_registry[task_id].get("dev_output")
        report = self.task_registry[task_id].get("specialist_report", "No report generated.")
        
        with self._get_lm_context(model_name, session_id):
            module = dspy.ChainOfThought(TestingExecutionSignature)
            result = module(
                problem_statement=json.dumps(problem_statement),
                architecture=json.dumps(architecture),
                dev_output=json.dumps(dev_output)
            )
            
            outcome_raw = result.team_outcome
            outcome_data = extract_json(outcome_raw)
            
        # Programmatically inject the detailed specialist test report
        outcome_data["detailed_test_report"] = report

        self._send_to_cos(task, task_id, {"team_outcome": outcome_data}, session_id, comm_type, model_name)
        return AgentResult(task_id=task_id, skip=True)

    def _send_to_cos(self, task, task_id, job_data, session_id, comm_type, model_name):
        target_id = "company-chief-of-staff-agent"
        job_data.update({
            "task_id": task_id,
            "user_request": self.task_registry[task_id].get("user_request"),
            "communication_type": comm_type,
            "session_id": session_id,
            "model_name": model_name
        })
        if comm_type == "delegate":
            self._log_to_his(target_id, job_data)
            self.context.delegator.submit_and_wait(subject_id=target_id, session_id=session_id, task_id=task_id, task_data=job_data)
        else:
            self._log_to_his(target_id, job_data)
            self.context.p2p_manager.send_sync(task=task, subject_id=target_id, job_data=job_data, session_id=session_id)

if __name__ == "__main__":
    main(TestingTeamLeadAgent)
