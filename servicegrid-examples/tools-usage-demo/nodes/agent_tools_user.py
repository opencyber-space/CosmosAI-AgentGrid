import time
import logging
from typing import List, Optional

from agents_sdk.core.agent_executor import AgentResult, AgentTask, Context
from agents_sdk.core.main import main
from agents_sdk.core.his import HisClient
from agents_functions import AgentFunctions
from agents_tools import AgentTools

log = logging.getLogger(__name__)

NODE_ID_MAPPING = {
    "agent-tool-user-demo": "my-agent-tool-user-demo"
}

NODE_TOOL_DEMO = "my-agent-tool-user-demo"

class ToolUsageDemoAgent:
    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        
        
        # Extract functions configuration from config.parameters.FUNCTIONS_CONFIG
        config_params = getattr(self.subject.persona, 'config', {}).get("parameters", {}) if hasattr(self.subject, 'persona') else {}
        tools_config = config_params.get("TOOLS_CONFIG", {})
        tools_registry_url = tools_config.get("tools_registry_url")
        llm_block_id = tools_config.get("llm_block_id")

        # Extract openai_api_key from models.llm_parameters
        self.api_key = ""
        integrations = getattr(self.subject, 'integrations', None)
        models = getattr(integrations, 'models', []) if integrations else []
        for model in models:
            if llm_block_id == model.llm_block_id:
                llm_params = getattr(model, 'llm_parameters', {}) if hasattr(model, 'llm_parameters') else (model.get('llm_parameters', {}) if isinstance(model, dict) else {})
                if "api_key" in llm_params:
                    self.api_key = llm_params["api_key"]
                    break

        if not self.api_key:
            raise Exception("API key not found")
        if not tools_registry_url:
            raise Exception("Tools registry URL not found")
        if not llm_block_id:
            raise Exception("LLM block ID not found")

        if "openai:" in llm_block_id:
            model_name = llm_block_id.replace("openai:", "")
            self.tools = AgentTools(tools_db_url=tools_registry_url, openai_api_key=self.api_key, gemini_api_key=None, model_name=model_name)
        elif "gemini:" in llm_block_id:
            model_name = llm_block_id.replace("gemini:", "")
            self.tools = AgentTools(tools_db_url=tools_registry_url, openai_api_key=None, gemini_api_key=self.api_key, model_name=model_name)

        # Register all tools upfront so their runtimes are ready before any search.
        self.tools.add("agentspace.commit-scribe.v4")
        self.tools.add("agentspace.log-detective.v4")
        self.tools.add("agentspace.schema-forge.v4")

        # Initialize HIS Client
        his_config = getattr(self.subject.persona, 'config', {}).get("parameters", {}).get("HIS_CONFIG", {}) if hasattr(self.subject, 'persona') else {}
        self.his_client = None
        if his_config:
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
            if self.his_client:
                self.his_client.submit(input_data=msg)
        except Exception:
            pass

    def get_muxer(self):
        return None

    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        log.info(f"Preprocessing task {task.task_id} {task.job_data}")
        job = task.job_data
        if "user_request" not in job:
            return None
        return [task]

    def on_data(self, task: AgentTask) -> AgentResult:
        try:
            job = task.job_data
            # Log incoming request
            self._log_to_his(
                target_id=NODE_TOOL_DEMO, # Self is target of incoming
                job_data={"task_type": "INCOMING_TASK", "payload": job}
            )

            response = self.tools.search_and_execute_tool(
                prompt="What tools can be used to analyse this data",
                input_dict={
                    "input": job
                }
            )
            print(response)

            job_output = response

            # Log outgoing result
            self._log_to_his(
                target_id="USER", # Terminal node
                job_data={"task_type": "OUTGOING_RESULT", "payload": job_output}
            )

            return AgentResult(
                task_id=task.task_id,
                job_output=job_output,
                job_output_metadata={},
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
    main(ToolUsageDemoAgent)
