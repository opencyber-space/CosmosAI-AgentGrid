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

class TestingDevSignature(dspy.Signature):
    """
    ### ROLE
    You are the Testing Developer Agent.

    ### TASK
    Create test scenarios based on the problem statement and system architecture.
    Refine these scenarios and execute validation on the developed product summary.
    Return a pass/fail status and a list of identified issues.

    ### OUTPUT
    Output EXACTLY a valid JSON block. All keys MUST be double-quoted.
    """
    problem_statement = dspy.InputField(desc="The product idea")
    architecture = dspy.InputField(desc="The system architecture design")
    dev_output = dspy.InputField(desc="The output summary from the developer team")
    deliverables = dspy.InputField(desc="The expected deliverables promised to the CoS")
    output_data = dspy.OutputField(desc="""Valid JSON block: {"test_scenarios": ["string"], "validation_results": "string", "status": "string", "issues": ["string"]}""")

class TestingDevModule(dspy.Module):
    def __init__(self, system_prompt):
        super().__init__()
        self.worker = dspy.ChainOfThought(TestingDevSignature)

    def forward(self, problem_statement, architecture, dev_output, deliverables):
        return self.worker(
            problem_statement=json.dumps(problem_statement), 
            architecture=json.dumps(architecture),
            dev_output=json.dumps(dev_output),
            deliverables=json.dumps(deliverables)
        )

class AgentPayloadProcessor:
    def prepare_payload(self, task: AgentTask):
        data = task.job_data
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

class TestingDevAgent:
    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        self.persona_default_system_message = getattr(self.subject.persona, 'default_system_message', "") if hasattr(self.subject, 'persona') else ""
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        self.module = TestingDevModule(self.persona_default_system_message)
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
        task_type = task.job_data.get("task_type")
        if task_type != "execute_task":
            log.warning("Task %s has task_type %s, which is not execute_task, skipping Testing Developer.", task.task_id, task_type)
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
            
            task_id = data.get("task_id", task.task_id)
            user_request = data.get("user_request")
            priority = data.get("priority", "Fast")
            
            raw_text, communication_type, model_name, session_id = self.payload_processor.prepare_payload(task)

            if task_id not in self.task_registry:
                self.task_registry[task_id] = {"user_request": user_request, "priority": priority}
            else:
                if user_request:
                    self.task_registry[task_id]["user_request"] = user_request
                if "priority" in data:
                    self.task_registry[task_id]["priority"] = priority

            # problem_statement is inside 'text' or passed directly
            text = data.get("text")
            problem_statement = json.loads(text) if isinstance(text, str) and text.startswith("{") else (data.get("problem_statement") or raw_text)

            architecture = data.get("architecture", "Architecture details")
            dev_output = data.get("dev_output", "Developer output summary")
            deliverables = data.get("deliverables", [])
            llm_session_id = data.get("session_id", str(uuid.uuid4()))

            with self.model_context.get_context(model_name=model_name, session_id=llm_session_id):
                result = self.module.forward(
                    problem_statement=problem_statement, 
                    architecture=architecture,
                    dev_output=dev_output,
                    deliverables=deliverables
                )
            
            output_raw = result.output_data
            output_data = extract_json(output_raw)

            job_data = {
                "task_type": "specialist_report",
                "specialist_report": output_data,
                "role": "Testing Developer",
                "session_id": llm_session_id,
                "model_name": model_name,
                "communication_type": communication_type,
                "task_id": task_id,
                "user_request": self.task_registry[task_id].get("user_request")
            }

            self._log_to_his("my-company-testing-team-lead-agent", job_data)
            return AgentResult(task_id=task.task_id, job_output=job_data, is_error=False)

        except Exception as e:
            log.exception(f"Error in Testing Dev: {e}")
            return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})

if __name__ == "__main__":
    main(TestingDevAgent)
