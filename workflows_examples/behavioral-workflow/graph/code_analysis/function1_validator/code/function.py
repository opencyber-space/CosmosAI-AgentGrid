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

    def _validate_and_optimize(self, code, description=""):
        prompt = (
            "You are an expert Python code reviewer.\n"
            "Analyze the following Python code and provide:\n"
            "1. A correctness check: identify any bugs, syntax errors, or logical issues.\n"
            "2. Optimization suggestions: performance improvements, Pythonic rewrites, better error handling.\n"
            "3. An optimized version of the code incorporating your suggestions.\n\n"
            "Respond ONLY in the following JSON format with no extra text:\n"
            "{\n"
            '  "is_valid": true or false,\n'
            '  "issues": ["issue1", "issue2"],\n'
            '  "optimizations": ["optimization1", "optimization2"],\n'
            '  "optimized_code": "...full rewritten code..."\n'
            "}\n\n"
        )
        if description:
            prompt += f"Code description: {description}\n\n"
        prompt += f"Code:\n```python\n{code}\n```"

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        return json.loads(response.choices[0].message.content)

    def eval(self, parameters, input_data, context):
        logger.info(f"[PolicyRule {self.rule_id}] Code validation started")

        code = input_data.get("code", "")
        description = input_data.get("description", "")

        if not code:
            return {"error": "No 'code' provided in input_data"}

        try:
            validation = self._validate_and_optimize(code, description)
            logger.info(
                f"Validation complete: is_valid={validation.get('is_valid')}, "
                f"issues={len(validation.get('issues', []))}, "
                f"optimizations={len(validation.get('optimizations', []))}"
            )
        except Exception as e:
            logger.error(f"Validation failed: {e}")
            return {"error": str(e)}

        # Pass the full incoming dict forward so downstream policies keep
        # 'code', 'function_name', 'description', etc., then attach results.
        return {
            **input_data,
            "code_validation": validation,
        }
