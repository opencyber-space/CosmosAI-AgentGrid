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


curl -X DELETE ${API_BASE_URL}/api/subjects/agent-workflow-collateral-evaluator

curl -X DELETE ${API_BASE_URL}/api/subjects/agent-workflow-financial-profile

curl -X DELETE ${API_BASE_URL}/api/subjects/agent-workflow-fraud-score

curl -X DELETE ${API_BASE_URL}/api/subjects/agent-workflow-identity-verification

curl -X DELETE ${API_BASE_URL}/api/subjects/agent-workflow-loan-decision

curl -X DELETE ${API_BASE_URL}/api/subjects/agent-workflow-loan-risk-router

curl -X DELETE ${API_BASE_URL}/api/subjects/agent-workflow-market-risk

curl -X DELETE ${API_BASE_URL}/api/subjects/agent-workflow-transaction-history


