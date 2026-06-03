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


curl -X POST ${API_BASE_URL}/api/remove-agent/deployer-123/agent-workflow-collateral-evaluator

curl -X POST ${API_BASE_URL}/api/remove-agent/deployer-123/agent-workflow-financial-profile

curl -X POST ${API_BASE_URL}/api/remove-agent/deployer-123/agent-workflow-fraud-score

curl -X POST ${API_BASE_URL}/api/remove-agent/deployer-123/agent-workflow-identity-verification

curl -X POST ${API_BASE_URL}/api/remove-agent/deployer-123/agent-workflow-loan-decision

curl -X POST ${API_BASE_URL}/api/remove-agent/deployer-123/agent-workflow-loan-risk-router

curl -X POST ${API_BASE_URL}/api/remove-agent/deployer-123/agent-workflow-market-risk

curl -X POST ${API_BASE_URL}/api/remove-agent/deployer-123/agent-workflow-transaction-history
