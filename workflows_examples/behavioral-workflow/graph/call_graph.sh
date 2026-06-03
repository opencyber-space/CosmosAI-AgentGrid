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

curl -X POST ${POLICY_DB_URL}/graph/execute_graph \
  -H "Content-Type: application/json" \
  -d '{
    "graph_uri": "code_analysis_pipeline_3:1.0-stable",
    "input_data": {
      "code": "def add(arg1, arg2):\n    return arg1 + arg2",
      "function_name": "add",
      "description": "Adds two numbers and returns the result"
    }
  }' | json_pp