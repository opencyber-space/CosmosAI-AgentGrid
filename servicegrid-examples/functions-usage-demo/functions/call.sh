#!/bin/bash
# Call each function individually via the job submission endpoint.
# Set OPENAI_API_KEY before running (or edit the api_key fields below).
#
# Usage:
#   OPENAI_API_KEY=sk-... ./call.sh
#   ./call.sh validator          - run only code-validator
#   ./call.sh generator          - run only test-case-generator
#   ./call.sh runner             - run only test-runner (requires test_cases in input)

GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$GIT_ROOT" ]; then
    GIT_ROOT=$(pwd) # Fallback if not run within git
fi
if [ -f "$GIT_ROOT/.env" ]; then
    set -a; source "$GIT_ROOT/.env"; set +a
else
    echo "Error: .env file MUST be present at $GIT_ROOT"
    exit 1
fi

API="http://${POLICY_DB_URL}"
OPENAI_KEY="${OPENAI_API_KEY:-<your-openai-api-key-here>}"
TARGET="${1:-all}"

SAMPLE_CODE='def add(a, b):\n    return a + b'
FUNCTION_NAME="add"
DESCRIPTION="Adds two numbers and returns the result"

# ---------------------------------------------------------------------------
# 1. code-validator
# ---------------------------------------------------------------------------
call_validator() {
  echo "=== Calling code-validator ==="
  curl -sS -X POST "${API}/jobs/submit/executor-001" \
    -H "Content-Type: application/json" \
    -d "$(cat <<EOF
{
  "name": "demo2-validator-job",
  "policy_rule_uri": "code-validator:1.4.0-stable",
  "policy_rule_parameters": {
    "openai_api_key": "${OPENAI_KEY}",
    "model": "gpt-4o-mini"
  },
  "node_selector": {},
  "inputs": {
    "code": "${SAMPLE_CODE}",
    "function_name": "${FUNCTION_NAME}",
    "description": "${DESCRIPTION}"
  }
}
EOF
)" | jq
}

# ---------------------------------------------------------------------------
# 2. test-case-generator  (expects code_validation from code-validator)
# ---------------------------------------------------------------------------
call_generator() {
  echo "=== Calling test-case-generator ==="
  curl -sS -X POST "${API}/jobs/submit/executor-001" \
    -H "Content-Type: application/json" \
    -d "$(cat <<EOF
{
  "name": "demo2-generator-job",
  "policy_rule_uri": "test-case-generator:1.0.0-stable",
  "policy_rule_parameters": {
    "openai_api_key": "${OPENAI_KEY}",
    "model": "gpt-4o-mini",
    "num_tests": 5
  },
  "node_selector": {},
  "inputs": {
    "code": "${SAMPLE_CODE}",
    "function_name": "${FUNCTION_NAME}",
    "description": "${DESCRIPTION}",
    "code_validation": {
      "is_valid": true,
      "issues": [],
      "optimizations": [],
      "optimized_code": "${SAMPLE_CODE}"
    }
  }
}
EOF
)" | jq
}

# ---------------------------------------------------------------------------
# 3. test-runner  (expects code_validation + test_cases)
# ---------------------------------------------------------------------------
call_runner() {
  echo "=== Calling test-runner ==="
  curl -sS -X POST "${API}/jobs/submit/executor-001" \
    -H "Content-Type: application/json" \
    -d "$(cat <<EOF
{
  "name": "demo2-runner-job",
  "policy_rule_uri": "test-runner:1.0.0-stable",
  "policy_rule_parameters": {},
  "node_selector": {},
  "inputs": {
    "code": "${SAMPLE_CODE}",
    "function_name": "${FUNCTION_NAME}",
    "code_validation": {
      "is_valid": true,
      "issues": [],
      "optimizations": [],
      "optimized_code": "${SAMPLE_CODE}"
    },
    "test_cases": [
      { "description": "positive numbers", "inputs": {"a": 1, "b": 2},   "expected_output": 3   },
      { "description": "zero + number",    "inputs": {"a": 0, "b": 5},   "expected_output": 5   },
      { "description": "negative numbers", "inputs": {"a": -3, "b": -2}, "expected_output": -5  },
      { "description": "floats",           "inputs": {"a": 1.5, "b": 2.5},"expected_output": 4.0 },
      { "description": "both zero",        "inputs": {"a": 0, "b": 0},   "expected_output": 0   }
    ]
  }
}
EOF
)" | jq
}

case "$TARGET" in
  validator)  call_validator ;;
  generator)  call_generator ;;
  runner)     call_runner ;;
  all)
    call_validator
    echo ""
    call_generator
    echo ""
    call_runner
    ;;
  *)
    echo "Unknown target: $TARGET"
    echo "Usage: $0 [validator|generator|runner|all]"
    exit 1
    ;;
esac
