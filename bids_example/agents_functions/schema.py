import os
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple, Optional, Callable
from uuid import uuid4

logger = logging.getLogger("FunctionPolicyUploader")
logger.setLevel(logging.INFO)


@dataclass
class FunctionEntry:
    # New fields
    function_name: str = ""                     
    function_version: str = ""                  
    function_release_tag: str = "stable"        

    function_id: str = ""                       
    function_metadata: Dict[str, Any] = field(default_factory=dict)
    function_search_description: str = ""
    function_tags: List[str] = field(default_factory=list)
    function_type: str = ""
    function_man_page_doc: str = ""
    function_code: str = ""                      
    function_policy_rule_uri: str = ""           
    function_settings: Dict[str, Any] = field(default_factory=dict)
    function_parameters: Dict[str, Any] = field(default_factory=dict)
    function_settings_schema: Dict[str, Any] = field(default_factory=dict)
    function_parameters_schema: Dict[str, Any] = field(default_factory=dict)
    function_input_schema: Dict[str, Any] = field(default_factory=dict)
    function_output_schema: Dict[str, Any] = field(default_factory=dict)

    function_api_spec: Dict[str, Any] = field(default_factory=dict)
    open_api_spec: Dict[str, Any] = field(default_factory=dict)
    api_parameters_to_cost_relation_data: Dict[str, Any] = field(default_factory=dict)
    is_system_action: bool = False
    is_stateful: bool = False
    is_external: bool = False
    external_function_url: str = ''
    external_headers: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FunctionEntry":
        return cls(
            function_name=data.get("function_name", ""),
            function_version=data.get("function_version", ""),
            function_release_tag=data.get("function_release_tag", "stable"),

            function_id=data.get("function_id", ""),
            is_stateful=data.get("is_stateful", False),
            function_metadata=dict(data.get("function_metadata", {})),
            function_search_description=data.get("function_search_description", ""),
            function_tags=list(data.get("function_tags", [])),
            function_type=data.get("function_type", ""),
            function_man_page_doc=data.get("function_man_page_doc", ""),
            function_code=data.get("function_code", ""),
            function_policy_rule_uri=data.get("function_policy_rule_uri", ""),
            function_settings=dict(data.get("function_settings", {})),
            function_parameters=dict(data.get("function_parameters", {})),
            function_settings_schema=dict(data.get("function_settings_schema", {})),
            function_parameters_schema=dict(data.get("function_parameters_schema", {})),
            function_input_schema=dict(data.get("function_input_schema", {})),
            function_output_schema=dict(data.get("function_output_schema", {})),
            function_api_spec=dict(data.get("function_api_spec", {})),
            open_api_spec=dict(data.get("open_api_spec", {})),
            api_parameters_to_cost_relation_data=dict(data.get("api_parameters_to_cost_relation_data", {})),
            is_system_action=bool(data.get("is_system_action", False)),
            is_external=bool(data.get("is_external", False)),
            external_function_url=data.get('external_function_url', ''),
            external_headers=data.get('external_headers', {})
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "function_name": self.function_name,
            "function_version": self.function_version,
            "function_release_tag": self.function_release_tag,

            "function_id": self.function_id,
            "function_metadata": dict(self.function_metadata),
            "function_search_description": self.function_search_description,
            "function_tags": list(self.function_tags),
            "function_type": self.function_type,
            "function_man_page_doc": self.function_man_page_doc,
            "function_code": self.function_code,
            "function_policy_rule_uri": self.function_policy_rule_uri,
            "function_settings": dict(self.function_settings),
            "function_parameters": dict(self.function_parameters),
            "function_settings_schema": dict(self.function_settings_schema),
            "function_parameters_schema": dict(self.function_parameters_schema),
            "function_input_schema": dict(self.function_input_schema),
            "function_output_schema": dict(self.function_output_schema),
            "function_api_spec": dict(self.function_api_spec),
            "open_api_spec": dict(self.open_api_spec),
            "api_parameters_to_cost_relation_data": dict(self.api_parameters_to_cost_relation_data),
            "is_system_action": bool(self.is_system_action),
            "is_stateful": False,
            "is_stateful": self.is_stateful,
            "external_function_url": self.external_function_url,
            "external_headers": self.external_headers
        }

    def generate_function_id(self) -> str:
       
        self.function_id = f"{self.function_name}:{self.function_version}-{self.function_release_tag}"
        return self.function_id
