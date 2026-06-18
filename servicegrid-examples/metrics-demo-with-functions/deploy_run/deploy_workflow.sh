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


curl -X POST ${API_BASE_URL}/api/deploy-workflow/deployer-123 -H "Content-Type: application/json" \
-d '
{
    "deployment_name": "simple-metrics-in-functions-workflow",
    "workflow_id": "simple-metrics-in-functions-workflow-001",
    "workflow_uri": "simple-metrics-in-functions-workflow:1.0.0-stable",
    "allocation": {
        "policy_db_url": "${POLICY_DB_URL}",
        "delegate_api_url": "${DELEGATE_API_URL}"
    }
}
'