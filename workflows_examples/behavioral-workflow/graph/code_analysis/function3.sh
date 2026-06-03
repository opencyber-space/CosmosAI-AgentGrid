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

curl -X POST ${POLICY_DB_URL}/function/deployments/create/executor-001 \
     -H "Content-Type: application/json" \
     -d '{
           "name": "test-runner-deployment",
           "policy_rule_uri": "test-runner:1.0-stable",
           "policy_rule_parameters": {},
           "replicas": 1,
           "autoscaling": false,
           "function_metadata": {"description": "Test Runner Deployment"},
           "function_tags": ["code-analysis", "testing", "executor"]
         }'
