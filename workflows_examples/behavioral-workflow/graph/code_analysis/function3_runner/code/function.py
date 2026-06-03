import logging
import traceback

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class AIOSv1PolicyRule:

    def __init__(self, rule_id, settings, parameters):
        self.rule_id = rule_id
        self.settings = settings or {}
        self.parameters = parameters or {}

    def _run_single_test(self, compiled_code, function_name, test_case):
        namespace = {}
        exec(compiled_code, namespace)

        func = namespace.get(function_name)
        if func is None:
            return {
                "status": "error",
                "error": f"Function '{function_name}' not found after exec",
                "description": test_case.get("description", ""),
                "inputs": test_case.get("inputs", {}),
                "expected_output": test_case.get("expected_output"),
                "actual_output": None,
                "passed": False,
            }

        inputs = test_case.get("inputs", {})
        expected = test_case.get("expected_output")
        description = test_case.get("description", "")

        try:
            actual_output = func(**inputs)
            passed = actual_output == expected
            return {
                "status": "ok",
                "description": description,
                "inputs": inputs,
                "expected_output": expected,
                "actual_output": actual_output,
                "passed": passed,
            }
        except Exception:
            return {
                "status": "error",
                "description": description,
                "inputs": inputs,
                "expected_output": expected,
                "actual_output": None,
                "passed": False,
                "error": traceback.format_exc(),
            }

    def eval(self, parameters, input_data, context):
        # input_data is policy2's enriched output, which contains:
        #   'code'            – original source code string
        #   'function_name'   – function to call
        #   'code_validation' – policy1's analysis (issues, optimizations, …)
        #   'test_cases'      – policy2's generated test cases
        logger.info(f"[PolicyRule {self.rule_id}] Test runner started")

        code = input_data.get("code", "")
        function_name = input_data.get("function_name", "")
        code_validation = input_data.get("code_validation", {})
        test_cases = input_data.get("test_cases", [])

        if not code:
            return {"error": "No 'code' found in input_data"}
        if not function_name:
            return {"error": "No 'function_name' found in input_data"}
        if not test_cases:
            return {
                "error": "No 'test_cases' found in input_data. Run policy2_test_gen before this policy.",
                "code_validation": code_validation,
            }

        # Compile once; surface syntax errors before running any test
        try:
            compiled_code = compile(code, "<policy_code>", "exec")
        except SyntaxError as e:
            return {"error": f"Syntax error in code: {e}"}

        # Execute every test case against the submitted code
        test_results = []
        for tc in test_cases:
            result = self._run_single_test(compiled_code, function_name, tc)
            test_results.append(result)
            status = "PASS" if result.get("passed") else "FAIL"
            logger.info(f"  [{status}] {tc.get('description', '')}")

        passed = sum(1 for r in test_results if r.get("passed"))
        total = len(test_results)

        return {
            # From policy1: correctness check + optimization suggestions
            "code_validation": code_validation,
            # From policy2: the inputs that were generated (without expected values)
            "test_inputs": [
                {
                    "description": tc.get("description", ""),
                    "inputs": tc.get("inputs", {}),
                }
                for tc in test_cases
            ],
            # From policy3: full execution results with actual vs expected
            "test_results": test_results,
            "summary": {
                "total": total,
                "passed": passed,
                "failed": total - passed,
            },
        }
