import time
import logging
from typing import List, Optional

from agents_sdk.core.agent_executor import AgentResult, AgentTask, Context
from agents_sdk.core.main import main
from agents_sdk.core.his import HisClient
from agents_functions import AgentFunctions

log = logging.getLogger(__name__)

NODE_ID_MAPPING = {
    "agent-code-creator-demo1-functions": "my-behavioral-code-creator",
    "agent-code-reviewer-demo1-functions": "my-behavioral-reviewer",
}

NODE_CODE_CREATOR = "my-behavioral-code-creator"
NODE_REVIEWER = "my-behavioral-reviewer"

class BehavioralReviewerAgent:
    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        
        # Extract openai_api_key from models.llm_parameters
        self.openai_api_key = ""
        integrations = getattr(self.subject, 'integrations', None)
        models = getattr(integrations, 'models', []) if integrations else []
        for model in models:
            llm_params = getattr(model, 'llm_parameters', {}) if hasattr(model, 'llm_parameters') else (model.get('llm_parameters', {}) if isinstance(model, dict) else {})
            if "api_key" in llm_params:
                self.openai_api_key = llm_params["api_key"]
                break
        
        # Fallback to config.parameters.api_key
        if not self.openai_api_key:
            self.openai_api_key = getattr(self.subject.persona, 'config', {}).get("parameters", {}).get("api_key", "")

        # Extract functions configuration from config.parameters.FUNCTIONS_CONFIG
        config_params = getattr(self.subject.persona, 'config', {}).get("parameters", {}) if hasattr(self.subject, 'persona') else {}
        functions_config = config_params.get("FUNCTIONS_CONFIG", {})
        
        functions_registry_url = functions_config.get("functions_registry_url")
        unique_parameter = functions_config.get("unique_parameter")
        executor_id = functions_config.get("executor_id")
        num_workers = functions_config.get("num_workers")
        
        self.agent_function = AgentFunctions(
            functions_registry_url=functions_registry_url,
            unique_parameter=unique_parameter,
            executor_id=executor_id,
            num_workers=int(num_workers)
        )
        self.agent_function.add("code-validator:1.4.0-stable")
        self.agent_function.add("test-generator:1.5.0-stable")
        self.agent_function.add("test-runner:1.0.0-stable")
        
        # Initialize HIS Client
        his_config = getattr(self.subject.persona, 'config', {}).get("parameters", {}).get("HIS_CONFIG", {}) if hasattr(self.subject, 'persona') else {}
        self.his_client = HisClient(
            base_url=his_config.get("HIS_BASE_URL", "http://localhost"),
            poll_interval=his_config.get("HIS_POLL_INTERVAL", 1.0),
            max_wait=his_config.get("HIS_MAX_WAIT", 60)
        )

    def _log_to_his(self, target_id, job_data):
        try:
            source_id = getattr(self.subject.identity, 'subject_id', 'unknown')
            target_id_mapped = {v: k for k, v in NODE_ID_MAPPING.items()}.get(target_id, target_id)
            msg = {"text": str(job_data), "source_id": source_id, "destination_id": target_id_mapped, "team": "Review Team", "timestamp": time.time()}
            self.his_client.submit(input_data=msg)
        except Exception:
            pass

    def get_muxer(self):
        return None

    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        log.info(f"Preprocessing task {task.task_id} {task.job_data}")
        job = task.job_data
        if not job.get("code"):
            if "final_project_outcome" not in job:
                log.warning("Task %s missing 'code' in job_data — skipping.", task.task_id)
                return None
        return [task]

    def on_data(self, task: AgentTask) -> AgentResult:
        try:
            job = task.job_data
            # Log incoming request
            self._log_to_his(
                target_id=NODE_REVIEWER, # Self is target of incoming
                job_data={"task_type": "INCOMING_TASK", "payload": job}
            )

            input_data = {
                "code": job["code"],
                "function_name": job.get("function_name", ""),
                "description": job.get("description", ""),
            }

            # Step 1: validate the code
            log.info("Calling code-validator:1.4.0-stable")
            result1 = self.agent_function.call(
                function_id="code-validator:1.4.0-stable",
                input_data={
                    **input_data,
                    "parameters": {
                        "openai_api_key": self.openai_api_key,
                        "model": "gpt-4o-mini"
                    }
                }
            )
            log.info("Code validator result: %s", result1)
            if isinstance(result1, dict) and "error" in result1:
                raise Exception(f"code-validator failed: {result1['error']}")

            # Step 2: generate test cases
            log.info("Calling test-generator:1.5.0-stable")
            result2 = self.agent_function.call(
                function_id="test-generator:1.5.0-stable",
                input_data={
                    **result1,
                    "parameters": {
                        "openai_api_key": self.openai_api_key,
                        "model": "gpt-4o-mini",
                        "num_tests": 5
                    }
                }
            )
            log.info("Test generator result: %s", result2)
            if isinstance(result2, dict) and "error" in result2:
                raise Exception(f"test-generator failed: {result2['error']}")

            # Step 3: run the generated tests against the code
            log.info("Calling test-runner:1.0.0-stable")
            result3 = self.agent_function.call(
                function_id="test-runner:1.0.0-stable",
                input_data={**result2}
            )
            if isinstance(result3, dict) and "error" in result3:
                raise Exception(f"test-runner failed: {result3['error']}")

            job_output = result3

            # Log outgoing result
            self._log_to_his(
                target_id="USER", # Terminal node
                job_data={"task_type": "OUTGOING_RESULT", "payload": job_output}
            )

            return AgentResult(
                task_id=task.task_id,
                job_output=job_output,
                job_output_metadata={"functions_called": ["code-validator:1.4.0-stable", "test-generator:1.5.0-stable", "test-runner:1.0.0-stable"]},
                is_error=False,
            )

        except Exception as e:
            log.exception("Task %s — unexpected error in on_data: %s", task.task_id, e)
            return AgentResult(
                task_id=task.task_id,
                is_error=True,
                error_data={"stage": "on_data", "message": str(e)},
            )

if __name__ == "__main__":
    main(BehavioralReviewerAgent)
