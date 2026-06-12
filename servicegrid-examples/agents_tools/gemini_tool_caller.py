import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from google import genai
from google.genai import types

from .db_client import ToolsRegistrySDK
from .tools_manager import ToolsExecutionManager

logger = logging.getLogger(__name__)

# Fields pulled from the tool schema for Gemini function definitions.
# Only these are sent to Gemini — not the full schema.
_SEARCH_FIELDS = ("tool_id", "tool_search_description", "tool_tags", "tool_api_spec")


def _sanitize_fn_name(tool_id: str) -> str:
    """Map a tool_id to a valid Gemini function name ([a-zA-Z0-9_-]{1,64})."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", tool_id)[:64]


def _build_gemini_function(tool: Dict) -> types.FunctionDeclaration:
    """
    Build one Gemini tool-calling function definition from selective schema fields.

    Uses:
      tool_id                            → function name (sanitized)
      tool_search_description + tool_tags → description sent to Gemini
      tool_api_spec.entrypoints.execute.input → parameter schema
    """
    tool_id = tool.get("tool_id", "")
    description = tool.get("tool_search_description", "No description provided.")
    tags = tool.get("tool_tags", [])
    if tags:
        description += f" Tags: {', '.join(tags)}."

    execute_input = (
        tool.get("tool_api_spec", {})
        .get("entrypoints", {})
        .get("execute", {})
        .get("input", {"type": "object", "properties": {}})
    )

    return types.FunctionDeclaration(
        name=_sanitize_fn_name(tool_id),
        description=description,
        parameters=execute_input,
    )


class GeminiToolCaller:
    """
    Integrates Gemini function-calling with the tools registry so that a natural-
    language prompt can automatically select and execute the right tool.

    Usage
    -----
    caller = GeminiToolCaller(
        registry_base_url="http://localhost:8080",
        gemini_api_key="...",
    )

    # Just find which tool fits the prompt:
    tool_id = caller.search_tool("Generate a conventional commit for my diff")

    # Find the tool, format the input, run it, return output:
    result = caller.search_and_execute_tool(
        prompt="Generate a conventional commit for my diff",
        input_dict={"diff": "diff --git a/auth.py ...", "branch_name": "fix/token"},
    )
    """

    def __init__(
        self,
        registry_base_url: str,
        gemini_api_key: str,
        model_name: str = "gemini-2.5-flash",
    ) -> None:
        self.sdk = ToolsRegistrySDK(registry_base_url)
        self.executor_manager = ToolsExecutionManager(registry_base_url)
        self.client = genai.Client(api_key=gemini_api_key)
        self.model = model_name

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_tools(self) -> List[Dict]:
        """Return all tools from the registry (broad search with no filters)."""
        try:
            result = self.sdk.list_all_tools()
            if isinstance(result, list):
                return result
            # Tolerate wrapped responses like {"tools": [...]} or {"data": [...]}
            return result.get("tools", result.get("data", []))
        except Exception as exc:
            logger.error(f"Failed to fetch tools from registry: {exc}")
            return []

    def _build_name_map(self, tools: List[Dict]) -> Dict[str, str]:
        """Return {sanitized_fn_name: original_tool_id} for reverse lookup."""
        mapping: Dict[str, str] = {}
        for tool in tools:
            tid = tool.get("tool_id", "")
            fn_name = _sanitize_fn_name(tid)
            # On collision append a counter suffix so every entry is reachable.
            if fn_name in mapping:
                counter = 2
                candidate = f"{fn_name}_{counter}"
                while candidate in mapping:
                    counter += 1
                    candidate = f"{fn_name}_{counter}"
                fn_name = candidate
            mapping[fn_name] = tid
        return mapping

    def _call_gemini(
        self,
        prompt: str,
        tools: List[Dict],
        input_dict: Optional[Dict] = None,
    ) -> Tuple[str, Dict]:
        """
        Send prompt (+ optional input_dict) to Gemini with all tool definitions
        and return (tool_id, formatted_args).

        Gemini selects the matching function and fills the arguments according to
        the tool's execute.input schema.
        """
        name_map = self._build_name_map(tools)
        # Rebuild function defs using the collision-safe name map so names match.
        fn_declarations = []
        for tool in tools:
            fn_decl = _build_gemini_function(tool)
            tid = tool.get("tool_id", "")
            # Find the (possibly suffixed) name assigned to this tool_id.
            for safe_name, mapped_id in name_map.items():
                if mapped_id == tid:
                    fn_decl.name = safe_name
                    break
            fn_declarations.append(fn_decl)

        user_content = prompt
        if input_dict:
            user_content += f"\n\nInput data (JSON):\n{json.dumps(input_dict, indent=2)}"

        # 1. Setup forced tool choice configuration (Equivalent to tool_choice="required")
        tool_config = types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(
                mode=types.FunctionCallingConfigMode.ANY  # Forces the model to call a tool
            )
        )

        # 2. Execute the request
        response = self.client.models.generate_content(
            model=self.model,
            contents=user_content,
            config=types.GenerateContentConfig(
                tools=[types.Tool(function_declarations=fn_declarations)],
                tool_config=tool_config,
            )
        )

        # 3. Extract the function name and arguments
        if not response.function_calls:
            raise ValueError("Gemini response did not contain a function call.")

        tool_call = response.function_calls[0]
        fn_name = tool_call.name
        raw_args: dict = tool_call.args  # Directly a dictionary!

        tool_id = name_map.get(fn_name)
        if not tool_id:
            raise ValueError(f"Gemini returned unknown function name: '{fn_name}'")

        formatted_args: Dict = raw_args if isinstance(raw_args, dict) else {}
        logger.info(f"Gemini selected tool='{tool_id}', args={formatted_args}")
        return tool_id, formatted_args

    def _ensure_registered(self, tool_id: str, tool_data: Dict) -> str:
        """Register tool with the executor manager if not already loaded."""
        instance_name = f"instance:{tool_id}"
        if instance_name not in self.executor_manager.tool_instances:
            creds = tool_data.get("default_tool_usage_credentials", {})
            self.executor_manager.register(instance_name, tool_id, {"tool_data": creds})
        return instance_name

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(
        self,
        prompt: str,
        input_dict: Optional[Dict] = None,
        tools: Optional[List[Dict]] = None,
    ) -> Tuple[str, Dict]:
        """
        Use Gemini to select the right tool and format *input_dict* against its
        schema.  Returns *(tool_id, formatted_args)* — no execution is performed.

        *tools* — pre-loaded tool records to use instead of fetching from the
        registry.  AgentTools passes the records already loaded by add() so no
        list endpoint is required.
        """
        if tools is None:
            tools = self._fetch_tools()
        if not tools:
            raise RuntimeError("No tools available. Add tools with tools.add() before searching.")
        return self._call_gemini(prompt, tools, input_dict)

    def search_tool(self, prompt: str) -> str:
        """Select the best matching tool for *prompt* and return its tool_id.
        No execution occurs."""
        tool_id, _ = self.resolve(prompt)
        return tool_id

    def search_and_execute_tool(
        self,
        prompt: str,
        input_dict: Dict[str, Any],
    ) -> Any:
        """
        Select the best matching tool, auto-format *input_dict* per its schema
        via Gemini function-calling, execute the tool, and return the output.

        Workflow
        --------
        1. Fetch all tools from the registry.
        2. Ask Gemini (with all tools as function definitions) to select the right
           tool and structure *input_dict* according to its execute.input schema.
        3. Parse the arguments returned by Gemini.
        4. Register and execute the tool with the formatted dict.
        5. Return the tool's output.

        Parameters
        ----------
        prompt : str
            Natural-language description of what needs to be done.
        input_dict : dict
            Raw input data; Gemini will validate and reshape it to match the
            selected tool's schema.

        Returns
        -------
        Any
            Output from the tool's execute() method.
        """
        tools = self._fetch_tools()
        if not tools:
            raise RuntimeError("No tools available in the registry.")

        tool_id, formatted_args = self._call_gemini(prompt, tools, input_dict)

        # Locate the full tool record so we can pass credentials on registration.
        tool_record = next((t for t in tools if t.get("tool_id") == tool_id), {})
        instance_name = self._ensure_registered(tool_id, tool_record)

        result = self.executor_manager.execute(instance_name, formatted_args)
        return result
