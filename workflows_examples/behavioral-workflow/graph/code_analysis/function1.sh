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
           "name": "code-validator-deployment-1",
           "policy_rule_uri": "code-validator:1.1-stable",
           "policy_rule_parameters": {
             "openai_api_key": "'${OPENAI_API_KEY}'",
             "model": "gpt-4o-mini"
           },
           "replicas": 1,
           "autoscaling": false,
           "function_metadata": {"description": "Code Validator Deployment"},
           "function_tags": ["code-analysis", "openai", "validation"]
         }'
