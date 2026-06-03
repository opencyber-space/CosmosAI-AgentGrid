#!/bin/bash

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

curl -X POST ${POLICY_UPLOAD_URL}/upload \
  -F "file=@./code_analysis/function2_test_gen/test-gen-01.zip" \
  -F "path=."

curl -X POST ${POLICY_UPLOAD_URL}/upload \
  -F "file=@./code_analysis/function1_validator/validator01.zip" \
  -F "path=."

curl -X POST ${POLICY_UPLOAD_URL}/upload \
  -F "file=@./code_analysis/function3_runner/runner-01.zip" \
  -F "path=."