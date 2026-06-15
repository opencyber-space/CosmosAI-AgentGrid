import logging
import os
from typing import List, Dict, Any, Optional

from .local_table import AgentAllowedTool
from .local_table import AgentAllowedToolAction
from .local_table import AgentAllowedToolStore
from .local_table import AgentAllowedToolActionStore
from .tools_manager import ToolsExecutionManager
from .db_client import ToolsRegistrySDK
from .openai_tool_caller import OpenAIToolCaller
from .gemini_tool_caller import GeminiToolCaller

logger = logging.getLogger("ToolsManager")
logger.setLevel(logging.INFO)


class AgentTools:
    def __init__(self, tools_db_url: str, openai_api_key: Optional[str] = None, gemini_api_key: Optional[str] = None, model_name: Optional[str] = None):
        self.tools_db_url = tools_db_url
        self.tool_store = AgentAllowedToolStore()
        self.action_store = AgentAllowedToolActionStore()
        self.executor = ToolsExecutionManager(self.tools_db_url)
        kwargs = {"model_name": model_name} if model_name else {}
        self._openai_caller: Optional[OpenAIToolCaller] = (
            OpenAIToolCaller(tools_db_url, openai_api_key, **kwargs) if openai_api_key else None
        )
        self._gemini_caller: Optional[GeminiToolCaller] = (
            GeminiToolCaller(tools_db_url, gemini_api_key, **kwargs) if gemini_api_key else None
        )

    def _require_openai(self) -> OpenAIToolCaller:
        if self._openai_caller is None:
            raise RuntimeError(
                "openai_api_key was not provided to AgentTools. "
                "Pass it in the constructor to use search_tool / search_and_execute_tool."
            )
        return self._openai_caller

    def _require_gemini(self) -> GeminiToolCaller:
        if self._gemini_caller is None:
            raise RuntimeError(
                "gemini_api_key was not provided to AgentTools. "
                "Pass it in the constructor to use search_tool / search_and_execute_tool with Gemini."
            )
        return self._gemini_caller

    def add_tool_to_org(self, tool_id: str, derived_from: str, mapping_org_id: str) -> bool:
        try:
            logger.info(f"Adding tool from DB: {tool_id}")
            response = ToolsRegistrySDK().get_tool_by_id(tool_id)
            if not response:
                logger.warning(f"Tool '{tool_id}' not found in DB.")
                return False

            tool = AgentAllowedTool.from_dict(response)
            tool.derived_from = derived_from
            tool.mapping_org_id = mapping_org_id
            return self.tool_store.create(tool)
        except Exception as e:
            logger.error(f"Failed to add tool '{tool_id}': {e}")
            return False

    def create_action(self,
                      action_type: str,
                      tool_ids: List[str],
                      action_tags: List[str],
                      action_metadata: Dict[str, Any],
                      action_search_description: str,
                      action_dsl: Dict[str, Any],
                      derived_from: str,
                      mapping_org_id: str) -> bool:
        try:
            missing = [tid for tid in tool_ids if not self.tool_store.get(tid)]
            if missing:
                logger.warning(
                    f"Cannot create action. Missing tools: {missing}")
                return False

            action = AgentAllowedToolAction(
                action_type=action_type,
                mapped_tool_ids=tool_ids,
                action_tags=action_tags,
                action_metadata=action_metadata,
                action_search_description=action_search_description,
                action_dsl=action_dsl,
                derived_from=derived_from,
                mapping_org_id=mapping_org_id
            )
            return self.action_store.create(action)
        except Exception as e:
            logger.error(f"Failed to create action '{action_type}': {e}")
            return False

    def add(self, tool_id, parameters={}) -> Any:
        try:
            instance_name = f"instance:{tool_id}"
            if instance_name not in self.executor.tool_instances:
                logger.info(
                    f"Tool '{tool_id}' not registered, registering now...")
                self.executor.register(instance_name, tool_id, parameters)
        except Exception as e:
            logger.error(f"Failed to execute tool '{tool_id}': {e}")
            raise

    def execute_tool_by_id(self, tool_id: str, input_data: Dict[str, Any]) -> Any:
        try:
            instance_name = f"instance:{tool_id}"
            if instance_name not in self.executor.tool_instances:
                logger.info(
                    f"Tool '{tool_id}' not registered, registering now...")
                self.executor.register(instance_name, tool_id)
            return self.executor.execute(instance_name, input_data)
        except Exception as e:
            logger.error(f"Failed to execute tool '{tool_id}': {e}")
            raise

    def _loaded_tool_records(self) -> List[Dict]:
        """Return tool_data dicts for every instance already loaded via add()."""
        return [v["tool_data"] for v in self.executor.tool_instances.values()]

    def search_tool(self, prompt: str, provider: str = "openai") -> str:
        """Return the tool_id best matching *prompt* using OpenAI or Gemini function-calling.
        Tools must be added with add() before calling this."""
        if provider == "gemini" or (self._gemini_caller and not self._openai_caller):
            tool_id, _ = self._require_gemini().resolve(prompt, tools=self._loaded_tool_records())
        else:
            tool_id, _ = self._require_openai().resolve(prompt, tools=self._loaded_tool_records())
        return tool_id

    def search_and_execute_tool(self, prompt: str, input_dict: Dict[str, Any], provider: str = "openai") -> Any:
        """Select the right tool for *prompt*, auto-format *input_dict* per its
        schema via OpenAI or Gemini, then execute using the shared executor (so tools
        pre-loaded with add() are reused without re-downloading).
        Tools must be added with add() before calling this."""
        loaded = self._loaded_tool_records()
        tool_model = input_dict.pop("tool_model", None)
        logger.info(f"Removed tool_model for search_and_execute_tool")
        if provider == "gemini" or (self._gemini_caller and not self._openai_caller):
            tool_id, formatted_args = self._require_gemini().resolve(prompt, input_dict, tools=loaded)
        else:
            tool_id, formatted_args = self._require_openai().resolve(prompt, input_dict, tools=loaded)
        instance_name = f"instance:{tool_id}"
        if instance_name not in self.executor.tool_instances:
            self.executor.register(instance_name, tool_id, {})
        if tool_model:
            formatted_args["tool_model"] = tool_model
            logger.info(f"Reinserted tool_model for search_and_execute_tool")
        return self.executor.execute(instance_name, formatted_args)

    def execute_command(self, tool_id: str, command, data):
        return self.executor.execute_command(
            f"instance:{tool_id}", command, data
        )
