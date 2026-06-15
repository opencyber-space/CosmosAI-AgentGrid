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

        api_key = self.parameters.get("openai_api_key") or self.settings.get("openai_api_key")
        self.client = None
        if api_key:
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

        if self.client is None:
            raise ValueError("LLM client not initialized. Please provide an API key.")

        if "gemini" in self.model:
            from google.genai import types
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                ),
            )
            return json.loads(response.text)
        else:
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

        logger.info("parameters",parameters)
        if "openai_api_key" in parameters:
            self.client = OpenAI(api_key=parameters.get("openai_api_key"))
        elif "tool_model" in parameters:
            self._create_client(parameters["tool_model"])
            logger.info(f"[code-validator] Created client for tool_model={parameters['tool_model']['llm_block_id']}")


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

        return {
            **input_data,
            "code_validation": validation,
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