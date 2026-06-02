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
    "agent-workflow-testing-team-lead": "my-company-testing-team-lead-agent",
    "agent-workflow-testing-dev": "my-company-testing-dev-agent"
}

# --- 1. The Signatures ---

class TestingEstimationSignature(dspy.Signature):
    """
    ### ROLE
    You are the Testing Team Lead.

    ### TASK
    Estimate the budget and effort for test planning and validation.
    
    ### OUTPUT
    Output EXACTLY a JSON block: {team_name, amount, deliverables}
    CRITICAL: The 'amount' field MUST be a single integer representing the total cost. DO NOT output 'amount' as a string (like "$18,000") or a dictionary.
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

# --- 2. The Testing Team Lead Agent ---

class TestingTeamLeadAgent:
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
            msg = {"text": str(job_data), "source_id": source_id, "destination_id": target_id_mapped, "team": "Testing Team", "timestamp": time.time()}
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
                log.info("Unpacking dynamic router payload in Testing Lead")
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
            
            # Initialize registry entry if not present
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

            raw_text, communication_type, model_name, session_id = self.payload_processor.prepare_payload(task)
            llm_session_id = data.get("session_id", str(uuid.uuid4()))

            # Consistent problem_statement extraction logic (Rule GEMINI.md)
            text = data.get("text")
            extracted = extract_json(text) if text else None
            
            problem_statement = data.get("problem_statement")
            if not problem_statement:
                problem_statement = extracted if isinstance(extracted, dict) else text
            
            if not problem_statement:
                problem_statement = self.task_registry[task_id].get("user_request", raw_text)

            if task_type == "process_artifact" and not data.get("artifact_data") and isinstance(extracted, dict):
                data["artifact_data"] = extracted

            if task_type == "process_artifact":
                src = data.get("artifact_data", {}).get("team_name", "")
                if "Arch" in src or "Senior" in src:
                    self.task_registry[task_id]["architecture"] = data.get("artifact_data")
                    log.info("Testing Team Lead received architecture for %s. Generating High-Level Test Plan...", task_id)
                    with self.model_context.get_context(model_name=model_name, session_id=llm_session_id):
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
                
                return self._check_and_trigger_testing(task, task_id, problem_statement, llm_session_id, model_name, communication_type)

            elif task_type == "estimate_budget":
                return self._handle_estimation(task, task_id, problem_statement, llm_session_id, model_name, communication_type)
            
            elif task_type == "execute_task":
                # Cache deliverables but DO NOT execute yet.
                self.task_registry[task_id]["deliverables"] = data.get("deliverables", [])
                log.info("Testing Team Lead cached execution parameters for %s. Awaiting Developer output.", task_id)
                return self._check_and_trigger_testing(task, task_id, problem_statement, llm_session_id, model_name, communication_type)
                
            elif task_type == "specialist_report":
                # Received test results from agent_testing_dev.py
                self.task_registry[task_id]["specialist_report"] = data.get("specialist_report")
                log.info("Testing Team Lead received final test results for %s. Synthesizing final outcome...", task_id)
                return self._finalize_execution(task, task_id, problem_statement, llm_session_id, model_name, communication_type)

            return AgentResult(task_id=task.task_id, skip=True)

        except Exception as e:
            log.exception(f"Error in Testing Team Lead: {e}")
            return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})

    def _handle_estimation(self, task, task_id, problem_statement, session_id, model_name, comm_type):
        with self.model_context.get_context(model_name=model_name, session_id=session_id):
            module = dspy.ChainOfThought(TestingEstimationSignature)
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
        self._log_to_his("my-chief-of-staff-agent", job_data)
        #return AgentResult(task_id=task.task_id, job_output=job_data, is_error=False)
        # Note: In if agent is a dynamic unit, then it can return job_output as [] or [{"nodeID":"", "input":{}}...] or {}
        # If  job_output={} then it is returned as it to the caller. If it is array then Workflow unit will break it down to whome to call next
        return AgentResult(
                task_id=task.task_id,
                job_output=job_data,
                job_output_metadata={"next_nodes": []},
                is_error=False,
            )

    def _check_and_trigger_testing(self, task, task_id, problem_statement, session_id, model_name, comm_type):
        registry = self.task_registry[task_id]
        if registry.get("deliverables") is not None and registry.get("dev_output") is not None:
            if not registry.get("module_test_cases"):
                log.info("Testing Team Lead generating module-specific test cases based on Developer Output...")
                with self.model_context.get_context(model_name=model_name, session_id=session_id):
                    module = dspy.ChainOfThought(TestingModuleTestCasesSignature)
                    res = module(
                        architecture=json.dumps(registry.get("architecture")),
                        dev_output=json.dumps(registry.get("dev_output")),
                        arch_design_test_cases=json.dumps(registry.get("arch_design_test_cases", []))
                    )
                    registry["module_test_cases"] = extract_json(res.module_test_cases)
                    log.info(f"Module Test Cases Generated: {registry['module_test_cases']}")

            log.info("Testing Team Lead has both deliverables and dev_output for %s. Triggering subordinates...", task_id)
            
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
            self._log_to_his("my-company-testing-dev-agent", job_data)
            input_for_testing_dev = [{"nodeID":"my-company-testing-dev-agent", "input":job_data}]
            return AgentResult(task_id=task.task_id, job_output=input_for_testing_dev, job_output_metadata={"next_nodes":["my-company-testing-dev-agent"]}, is_error=False)
        else:
            log.info("Testing Team Lead awaiting dependencies for %s. Deliverables: %s | Dev Output: %s",
                     task_id,
                     "Cached" if registry.get("deliverables") is not None else "Missing",
                     "Cached" if registry.get("dev_output") is not None else "Missing")
            return AgentResult(task_id=task.task_id, job_output={}, job_output_metadata={"next_nodes":[]}, is_error=False)

    def _finalize_execution(self, task, task_id, problem_statement, session_id, model_name, comm_type):
        architecture = self.task_registry[task_id].get("architecture")
        dev_output = self.task_registry[task_id].get("dev_output")
        report = self.task_registry[task_id].get("specialist_report", "No report generated.")
        
        with self.model_context.get_context(model_name=model_name, session_id=session_id):
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
        outcome_data["team_name"] = "Testing Team Lead"

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
        return AgentResult(task_id=task.task_id, job_output=job_data, job_output_metadata={"next_nodes":[]}, is_error=False)

if __name__ == "__main__":
    main(TestingTeamLeadAgent)
