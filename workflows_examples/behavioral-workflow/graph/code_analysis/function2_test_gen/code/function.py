import json
import logging
from openai import OpenAI

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class AIOSv1PolicyRule:

    def __init__(self, rule_id, settings, parameters):
        self.rule_id = rule_id
        self.settings = settings or {}
        self.parameters = parameters or {}

        api_key = self.parameters.get("openai_api_key") or self.settings.get("openai_api_key")
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
            "Respond ONLY in the following JSON format with no extra text:\n"
            "{\n"
            '  "function_name": "<function_name>",\n'
            '  "test_cases": [\n'
            '    {\n'
            '      "description": "short human-readable label",\n'
            '      "inputs": {"arg1": <value>, "arg2": <value>},\n'
            '      "expected_output": <value>\n'
            '    }\n'
            '  ]\n'
            "}\n\n"
            f"Code:\n```python\n{code}\n```"
        )

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        return json.loads(response.choices[0].message.content)

    def eval(self, parameters, input_data, context):
        # input_data here is policy1's enriched output dict, which already
        # contains 'code', 'function_name', and 'code_validation'.
        logger.info(f"[PolicyRule {self.rule_id}] Test generation started")

        code = input_data.get("code", "")
        function_name = input_data.get("function_name", "")

        if not code:
            return {"error": "No 'code' found in input_data (expected to be passed through from policy1)"}
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

        # Continue enriching the dict forward; policy3 will receive everything.
        return {
            **input_data,
            "test_cases": result.get("test_cases", []),
        }
