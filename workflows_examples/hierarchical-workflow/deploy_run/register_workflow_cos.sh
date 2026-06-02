#!/bin/bash
GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$GIT_ROOT" ]; then GIT_ROOT=$(pwd); fi
if [ -f "$GIT_ROOT/.env" ]; then set -a; source "$GIT_ROOT/.env"; set +a; else echo "Error: .env file MUST be present at $GIT_ROOT"; exit 1; fi

curl -X POST "${API_BASE_URL}/api/workflows" \
  -H "Content-Type: application/json" \
  -d @$GIT_ROOT/workflows_examples/hierarchical-workflow/deploy_run/workflow-cos.json
echo -e "\nCOS sub-workflow registered successfully!"
