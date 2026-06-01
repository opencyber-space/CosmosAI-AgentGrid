#!/bin/bash
GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$GIT_ROOT" ]; then GIT_ROOT=$(pwd); fi
if [ -f "$GIT_ROOT/.env" ]; then set -a; source "$GIT_ROOT/.env"; set +a; else echo "Error: .env file MUST be present at $GIT_ROOT"; exit 1; fi

curl -X POST ${API_BASE_URL}/api/deploy-workflow/deployer-123 -H "Content-Type: application/json" \
-d '
{
    "deployment_name": "workflow-financial-team",
    "workflow_id": "workflow-financial-team",
    "workflow_uri": "workflow-financial-team:1.0.0-production",
    "allocation": {
        "policy_db_url": "${POLICY_DB_URL}",
        "delegate_api_url": "${DELEGATE_API_URL}"
    }
}
'
echo -e "\nFinance sub-workflow deployed successfully!"
