import json
import logging
import time
import sys
import os

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from openai import OpenAI
from google import genai
from metrics_util import AgentMetrics

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class AIOSv1PolicyRule:

    def __init__(self, rule_id, settings, parameters):
        self.rule_id = rule_id
        self.settings = settings or {}
        self.parameters = parameters or {}
        print(settings,parameters)

        self.user_task_id = self.parameters.get("user_task_id", "")
        self.task_id = self.parameters.get("task_id", "")

        api_key = self.parameters.get("openai_api_key",None) or self.settings.get("openai_api_key",None)
        self.client = None
        if api_key:
            self.client = OpenAI(api_key=api_key)
        self.model = self.parameters.get("model", "gpt-4o-mini")
        self.num_tests = int(self.parameters.get("num_tests", 5))

        # Sanitize rule_id for namespace (Prometheus requires alphanumeric/underscore)
        sanitized_rule_id = "".join(c if c.isalnum() or c == '_' else '_' for c in (self.rule_id or ""))
        ns = sanitized_rule_id if sanitized_rule_id else "test_case_generator"
        self.metrics = AgentMetrics(namespace=ns)

    def _generate_tests(self, code, function_name):
        prompt = (
            "You are an expert Python test engineer.\n"
            f"Generate {self.num_tests} diverse test cases for the Python function `{function_name}`.\n"
            "Cover: normal inputs, edge cases, and boundary conditions.\n"
            "Every value in `inputs` and `expected_output` must be a plain JSON-serializable type "
            "(string, number, boolean, list, dict, or null).\n\n"
            "Respond ONLY in the following JSON format with no extra text. "
            "Crucially, the keys in the `inputs` dictionary must match the exact parameter names of the function "
            "defined in the code (for example, if the function is `def add(a, b):`, the inputs keys must be `\"a\"` and `\"b\"`):\n"
            "{\n"
            '  "function_name": "<function_name>",\n'
            '  "test_cases": [\n'
            '    {\n'
            '      "description": "short human-readable label",\n'
            '      "inputs": {"<parameter_name_1>": <value>, "<parameter_name_2>": <value>},\n'
            '      "expected_output": <value>\n'
            '    }\n'
            '  ]\n'
            "}\n\n"
            f"Code:\n```python\n{code}\n```"
        )

        if self.client is None:
            raise ValueError("LLM client not initialized. Please provide an API key.")

        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0
        start_time = time.time()

        try:
            if "gemini" in self.model:
                from google.genai import types
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                    ),
                )
                duration = time.time() - start_time
                usage = getattr(response, "usage_metadata", None)
                if usage:
                    prompt_tokens = getattr(usage, "prompt_token_count", 0) or getattr(usage, "prompt_tokens", 0) or 0
                    completion_tokens = getattr(usage, "candidates_token_count", 0) or getattr(usage, "completion_tokens", 0) or 0
                    total_tokens = getattr(usage, "total_token_count", 0) or getattr(usage, "total_tokens", 0) or 0
                result_dict = json.loads(response.text)
            else:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                )
                duration = time.time() - start_time
                usage = getattr(response, "usage", None)
                if usage:
                    prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
                    completion_tokens = getattr(usage, "completion_tokens", 0) or 0
                    total_tokens = getattr(usage, "total_tokens", 0) or 0
                result_dict = json.loads(response.choices[0].message.content)

            self.metrics.increment_llm_calls(self.model, "success", self.rule_id, user_task_id=self.user_task_id, task_id=self.task_id)
            self.metrics.observe_llm_call_duration(self.model, "success", duration, self.rule_id, user_task_id=self.user_task_id, task_id=self.task_id)
            if prompt_tokens > 0:
                self.metrics.increment_llm_prompt_tokens(self.model, prompt_tokens, self.rule_id, user_task_id=self.user_task_id, task_id=self.task_id)
            if completion_tokens > 0:
                self.metrics.increment_llm_completion_tokens(self.model, completion_tokens, self.rule_id, user_task_id=self.user_task_id, task_id=self.task_id)
            if total_tokens > 0:
                self.metrics.increment_llm_total_tokens(self.model, total_tokens, self.rule_id, user_task_id=self.user_task_id, task_id=self.task_id)

            return result_dict

        except Exception as e:
            duration = time.time() - start_time
            self.metrics.increment_llm_calls(self.model, "failed", self.rule_id, user_task_id=self.user_task_id, task_id=self.task_id)
            self.metrics.increment_llm_errors(self.model, type(e).__name__, self.rule_id, user_task_id=self.user_task_id, task_id=self.task_id)
            self.metrics.observe_llm_call_duration(self.model, "failed", duration, self.rule_id, user_task_id=self.user_task_id, task_id=self.task_id)
            raise e

    def eval(self, parameters, input_data, context):
        self.user_task_id = parameters.get("user_task_id", "") or self.parameters.get("user_task_id", "")
        self.task_id = parameters.get("task_id", "") or self.parameters.get("task_id", "")

        logger.info(f"[PolicyRule {self.rule_id}] Test generation started")

        code = input_data.get("code", "")
        function_name = input_data.get("function_name", "")

        logger.info(f"parameters: {parameters}")

        if "tool_model" in parameters:
            self._create_client(parameters["tool_model"])
            logger.info(f"[code-validator] Created client for tool_model={parameters['tool_model']['llm_block_id']}")


        if not code:
            return {"error": "No 'code' found in input_data (expected to be passed through from code-validator)"}
        if not function_name:
            return {"error": "No 'function_name' found in input_data"}

        try:
            result = self._generate_tests(code, function_name)
            logger.info(
                f"Generated {len(result.get('test_cases', []))} test cases "
                f"for function '{function_name}'"
            )
        except Exception as e:
            logger.error(f"Test generation failed: {e}")
            return {"error": str(e)}

        return {
            **input_data,
            "test_cases": result.get("test_cases", []),
        }

    def _create_client(self, model_dict: dict):
        model_type = model_dict["llm_type"]
        model_name = model_dict["llm_block_id"]
        api_key = model_dict["llm_parameters"]["api_key"]
        llm_parameters = model_dict["llm_parameters"]
        del llm_parameters["api_key"]
        if "openai" in model_name:
            self.model = model_name.split(":")[-1]
            self.client = OpenAI(api_key=api_key)
        elif "gemini" in model_name:
            self.model = model_name.split(":")[-1]
            self.client = genai.Client(api_key=api_key)
