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
}

class StrategySignature(dspy.Signature):
    """
    ### ROLE
    You are the Digital Marketing Strategy Agent.
    ### TASK
    Suggest social media and ads strategy. Define audience targeting.
    ### OUTPUT
    Output EXACTLY a valid JSON block. All keys MUST be double-quoted.
    """
    problem_statement = dspy.InputField(desc="The problem statement")
    output_data = dspy.OutputField(desc="""Valid JSON block: {"strategy": "string", "audience_targeting": "string", "deliverables": ["string"]}""")

class StrategyModule(dspy.Module):
    def __init__(self, system_prompt):
        super().__init__()
        self.worker = dspy.ChainOfThought(StrategySignature)
    def forward(self, problem_statement):
        return self.worker(problem_statement=json.dumps(problem_statement))

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

class MarketingStrategyAgent:
    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        self.persona_default_system_message = getattr(self.subject.persona, 'default_system_message', "") if hasattr(self.subject, 'persona') else ""
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        self.module = StrategyModule(self.persona_default_system_message)
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
        text = task.job_data.get("text")
        if not text and "problem_statement" not in task.job_data:
            log.warning("Task %s has no 'text' or 'problem_statement' in job_data, skipping.", task.task_id)
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

            text = data.get("text")
            problem_statement = json.loads(text) if isinstance(text, str) and text.startswith("{") else (data.get("problem_statement") or raw_text)
            llm_session_id = data.get("session_id", str(uuid.uuid4()))

            with self.model_context.get_context(model_name=model_name, session_id=llm_session_id):
                result = self.module.forward(problem_statement=problem_statement)
            
            output_raw = result.output_data
            output_data = extract_json(output_raw)
            
            task_type = data.get("task_type", "estimate_budget")
            
            if task_type == "execute_task":
                job_data = {
                    "task_type": "specialist_report",
                    "specialist_report": {
                        "team_name": "Digital Strategy",
                        "details": output_data
                    },
                    "session_id": llm_session_id,
                    "model_name": model_name,
                    "communication_type": communication_type,
                    "task_id": task_id,
                    "user_request": self.task_registry[task_id].get("user_request")
                }
            else:
                job_data = {
                    "communication_type": communication_type,
                    "budget_estimate": {
                        "team_name": "Digital Strategy",
                        "deliverables": output_data.get("deliverables", ["Report"])
                    },
                    "details": output_data,
                    "session_id": llm_session_id,
                    "model_name": model_name,
                    "task_id": task_id,
                    "user_request": self.task_registry[task_id].get("user_request")
                }
            
            self._log_to_his("my-marketing-team-lead-agent", job_data)
            return AgentResult(task_id=task.task_id, job_output=job_data, is_error=False)

        except Exception as e:
            log.exception(f"Error in Strategy Agent: {e}")
            return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})

if __name__ == "__main__":
    main(MarketingStrategyAgent)
