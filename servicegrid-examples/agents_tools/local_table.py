from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
import requests

import logging


logger = logging.getLogger("AgentAllowedToolActionStore")
logger.setLevel(logging.INFO)


@dataclass
class AgentAllowedTool:
    tool_id: str = ''
    tool_metadata: Dict[str, Any] = field(default_factory=dict)
    tool_search_description: str = ''
    tool_tags: List[str] = field(default_factory=list)
    tool_type: str = ''
    tool_man_page_doc: str = ''
    tool_api_spec: Dict[str, Any] = field(default_factory=dict)
    tool_custom_actions_dsl_map: Dict[str, Any] = field(default_factory=dict)
    default_tool_usage_credentials: Dict[str, Any] = field(
        default_factory=dict)
    derived_from: str = ''
    mapping_org_id: str = ''

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentAllowedTool":
        return cls(
            tool_id=data.get("tool_id", ""),
            tool_metadata=data.get("tool_metadata", {}),
            tool_search_description=data.get("tool_search_description", ""),
            tool_tags=data.get("tool_tags", []),
            tool_type=data.get("tool_type", ""),
            tool_man_page_doc=data.get("tool_man_page_doc", ""),
            tool_api_spec=data.get("tool_api_spec", {}),
            tool_custom_actions_dsl_map=data.get(
                "tool_custom_actions_dsl_map", {}),
            default_tool_usage_credentials=data.get(
                "default_tool_usage_credentials", {}),
            derived_from=data.get("derived_from", ""),
            mapping_org_id=data.get("mapping_org_id", "")
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "tool_metadata": self.tool_metadata,
            "tool_search_description": self.tool_search_description,
            "tool_tags": self.tool_tags,
            "tool_type": self.tool_type,
            "tool_man_page_doc": self.tool_man_page_doc,
            "tool_api_spec": self.tool_api_spec,
            "tool_custom_actions_dsl_map": self.tool_custom_actions_dsl_map,
            "default_tool_usage_credentials": self.default_tool_usage_credentials,
            "derived_from": self.derived_from,
            "mapping_org_id": self.mapping_org_id
        }


@dataclass
class AgentAllowedToolAction:
    action_type: str = ''
    mapped_tool_ids: List[str] = field(default_factory=list)
    action_tags: List[str] = field(default_factory=list)
    action_metadata: Dict[str, Any] = field(default_factory=dict)
    action_search_description: str = ''
    action_dsl: Dict[str, Any] = field(default_factory=dict)
    derived_from: str = ''
    mapping_org_id: str = ''

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentAllowedToolAction":
        return cls(
            action_type=data.get("action_type", ""),
            mapped_tool_ids=data.get("mapped_tool_ids", []),
            action_tags=data.get("action_tags", []),
            action_metadata=data.get("action_metadata", {}),
            action_search_description=data.get(
                "action_search_description", ""),
            action_dsl=data.get("action_dsl", {}),
            derived_from=data.get("derived_from", ""),
            mapping_org_id=data.get("mapping_org_id", "")
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_type": self.action_type,
            "mapped_tool_ids": self.mapped_tool_ids,
            "action_tags": self.action_tags,
            "action_metadata": self.action_metadata,
            "action_search_description": self.action_search_description,
            "action_dsl": self.action_dsl,
            "derived_from": self.derived_from,
            "mapping_org_id": self.mapping_org_id
        }


class AgentAllowedToolStore:
    def __init__(self):
        self._store: Dict[str, AgentAllowedTool] = {}

    def create(self, tool: AgentAllowedTool) -> bool:
        if tool.tool_id in self._store:
            logger.warning(f"Tool '{tool.tool_id}' already exists.")
            return False
        self._store[tool.tool_id] = tool
        logger.info(f"Tool '{tool.tool_id}' added.")
        return True

    def get(self, tool_id: str) -> Optional[AgentAllowedTool]:
        return self._store.get(tool_id)

    def update(self, tool_id: str, updates: Dict) -> bool:
        tool = self._store.get(tool_id)
        if not tool:
            logger.warning(f"Tool '{tool_id}' not found for update.")
            return False
        for key, value in updates.items():
            if hasattr(tool, key):
                setattr(tool, key, value)
        logger.info(f"Tool '{tool_id}' updated.")
        return True

    def delete(self, tool_id: str) -> bool:
        if tool_id in self._store:
            del self._store[tool_id]
            logger.info(f"Tool '{tool_id}' deleted.")
            return True
        logger.warning(f"Tool '{tool_id}' not found for deletion.")
        return False

    def list_all(self) -> List[AgentAllowedTool]:
        return list(self._store.values())


class AgentAllowedToolActionStore:
    def __init__(self):
        self._store: Dict[str, AgentAllowedToolAction] = {}

    def _get_key(self, action: AgentAllowedToolAction) -> str:
        return f"{action.action_type}:{action.mapping_org_id}"

    def create(self, action: AgentAllowedToolAction) -> bool:
        key = self._get_key(action)
        if key in self._store:
            logger.warning(f"Action '{key}' already exists.")
            return False
        self._store[key] = action
        logger.info(f"Action '{key}' added.")
        return True

    def get(self, action_type: str, mapping_org_id: str) -> Optional[AgentAllowedToolAction]:
        return self._store.get(f"{action_type}:{mapping_org_id}")

    def update(self, action_type: str, mapping_org_id: str, updates: Dict) -> bool:
        key = f"{action_type}:{mapping_org_id}"
        action = self._store.get(key)
        if not action:
            logger.warning(f"Action '{key}' not found for update.")
            return False
        for k, v in updates.items():
            if hasattr(action, k):
                setattr(action, k, v)
        logger.info(f"Action '{key}' updated.")
        return True

    def delete(self, action_type: str, mapping_org_id: str) -> bool:
        key = f"{action_type}:{mapping_org_id}"
        if key in self._store:
            del self._store[key]
            logger.info(f"Action '{key}' deleted.")
            return True
        logger.warning(f"Action '{key}' not found for deletion.")
        return False

    def list_all(self) -> List[AgentAllowedToolAction]:
        return list(self._store.values())


class ToolsManagement:
    def __init__(self, tools_db_url: str):
        self.tools_db_url = tools_db_url.rstrip("/")
        self.tool_store = AgentAllowedToolStore()
        self.action_store = AgentAllowedToolActionStore()

    def add_tool_for_agent(self, tool_id: str, derived_from: str, mapping_org_id: str) -> bool:
        try:
            url = f"{self.tools_db_url}/tools/{tool_id}"
            response = requests.get(url)
            if response.status_code != 200:
                logger.error(f"Failed to fetch tool '{tool_id}' from DB: {response.status_code}")
                return False

            tool_data = response.json()
            tool = AgentAllowedTool.from_dict(tool_data)
            tool.derived_from = derived_from
            tool.mapping_org_id = mapping_org_id

            return self.tool_store.create(tool)
        except Exception as e:
            logger.error(f"Exception while adding tool '{tool_id}': {e}")
            return False

    def create_action(self,
                      action_type: str,
                      tool_ids: List[str],
                      action_tags: List[str],
                      action_metadata: Dict[str, any],
                      action_search_description: str,
                      action_dsl: Dict[str, any],
                      derived_from: str,
                      mapping_org_id: str) -> bool:
        try:
            missing = [tid for tid in tool_ids if self.tool_store.get(tid) is None]
            if missing:
                logger.warning(f"Cannot create action. Missing tools: {missing}")
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
            logger.error(f"Exception while creating action '{action_type}': {e}")
            return False

    def list_agent_tools(self) -> List[AgentAllowedTool]:
        return self.tool_store.list_all()

    def list_agent_actions(self) -> List[AgentAllowedToolAction]:
        return self.action_store.list_all()

    def get_tool(self, tool_id: str) -> Optional[AgentAllowedTool]:
        return self.tool_store.get(tool_id)

    def get_action(self, action_type: str, mapping_org_id: str) -> Optional[AgentAllowedToolAction]:
        return self.action_store.get(action_type, mapping_org_id)



