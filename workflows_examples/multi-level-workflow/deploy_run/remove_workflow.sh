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


# curl -X POST ${API_BASE_URL}/api/remove-workflow/deployer-111/workflow-fraud-investigation \
# -H "Content-Type: application/json" \
# -d '
# {
# }
# '

curl -X POST ${API_BASE_URL}/api/remove-workflow/deployer-111/workflow-loan-risk-assessment \
-H "Content-Type: application/json" \
-d '
{
}
'