import logging
import uuid
import json
import dspy
from typing import Any, Dict, List, Optional

from agents_sdk.core.agent_executor import AgentResult, AgentTask, Context
from agents_sdk.core.main import main
from agents_sdk.core.his import HisClient
from utils.dspy_aios_llms import AIOS_DSPy_LMs
from utils.json_utils import extract_json

log = logging.getLogger(__name__)

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

class TestingDevAgent:
    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        self.persona_default_system_message = self.subject.persona.default_system_message
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        self.module = TestingDevModule(self.persona_default_system_message)
        self.task_registry = {}
        # Initialize HIS Client
        his_config = self.subject.persona.config.get("parameters", {}).get("HIS_CONFIG", {})
        self.his_client = HisClient(
            base_url=his_config["HIS_BASE_URL"],
            poll_interval=his_config.get("HIS_POLL_INTERVAL", 1.0),
            max_wait=his_config.get("HIS_MAX_WAIT", 60)
        )



    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        log.info(f"Preprocessing task {task.task_id} {task.job_data}")
        text = task.job_data.get("text")
        if not text:
            # Check for problem_statement or architecture
            if "problem_statement" in task.job_data or "architecture" in task.job_data:
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

            # problem_statement is inside 'text' or passed directly
            text = data.get("text")
            problem_statement = json.loads(text) if isinstance(text, str) and text.startswith("{") else data.get("problem_statement")

            architecture = data.get("architecture", "Architecture details")
            dev_output = data.get("dev_output", "Developer output summary")
            deliverables = data.get("deliverables", [])
            llm_session_id = str(uuid.uuid4())
            model_name = data.get("model_name", "aios:qwen3-1-7b-vllm-block")
            communication_type = data.get("communication_type", "delegate")

            with dspy.settings.context(lm=self.aios_dspy_lm.get_choosen_model(model_name=model_name, session_id=llm_session_id)):
                result = self.module.forward(
                    problem_statement=problem_statement, 
                    architecture=architecture,
                    dev_output=dev_output,
                    deliverables=deliverables
                )
            
            output_raw = result.output_data
            output_data = extract_json(output_raw)

            parent_id = "company-testing-team-lead"
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

            if communication_type == "delegate":
                self._log_to_his(parent_id, job_data)
                self.context.delegator.submit_and_wait(subject_id=parent_id, session_id=llm_session_id, task_id=task.task_id, task_data=job_data)
            else:
                self._log_to_his(parent_id, job_data)
                self.context.p2p_manager.send_sync(task=task, subject_id=parent_id, job_data=job_data, session_id=llm_session_id)

            return AgentResult(task_id=task.task_id, skip=True)

        except Exception as e:
            log.exception(f"Error in Testing Dev: {e}")
            return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})

if __name__ == "__main__":
    main(TestingDevAgent)
