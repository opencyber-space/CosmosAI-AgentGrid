import json
import logging
from openai import OpenAI
from google import genai

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class AIOSv1PolicyRule:

    def __init__(self, rule_id, settings, parameters):
        self.rule_id = rule_id
        self.settings = settings or {}
        self.parameters = parameters or {}
        print(settings,parameters)

        api_key = self.parameters.get("openai_api_key",None) or self.settings.get("openai_api_key",None)
        self.client = None
        if api_key:
            self.client = OpenAI(api_key=api_key)
        self.model = self.parameters.get("model", "gpt-4o-mini")
        self.num_tests = int(self.parameters.get("num_tests", 5))

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
            return {"error": "OpenAI client not initialized. Missing API key."}

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        return json.loads(response.choices[0].message.content)

    def eval(self, parameters, input_data, context):
        logger.info(f"[PolicyRule {self.rule_id}] Test generation started")

        code = input_data.get("code", "")
        function_name = input_data.get("function_name", "")

        logger.info("parameters",parameters)

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
