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


envsubst < "./agent_workflow_collateral_evaluator.json" > "./agent_workflow_collateral_evaluator_evaluated.json"
curl -X POST \
    -H "Content-Type: application/json" \
    -d @"./agent_workflow_collateral_evaluator_evaluated.json" \
    ${API_BASE_URL}/api/subjects
rm -f "./agent_workflow_collateral_evaluator_evaluated.json"

envsubst < "./agent_workflow_financial_profile.json" > "./agent_workflow_financial_profile_evaluated.json"
curl -X POST \
    -H "Content-Type: application/json" \
    -d @"./agent_workflow_financial_profile_evaluated.json" \
    ${API_BASE_URL}/api/subjects
rm -f "./agent_workflow_financial_profile_evaluated.json"

envsubst < "./agent_workflow_fraud_score.json" > "./agent_workflow_fraud_score_evaluated.json"
curl -X POST \
    -H "Content-Type: application/json" \
    -d @"./agent_workflow_fraud_score_evaluated.json" \
    ${API_BASE_URL}/api/subjects
rm -f "./agent_workflow_fraud_score_evaluated.json"

envsubst < "./agent_workflow_identity_verification.json" > "./agent_workflow_identity_verification_evaluated.json"
curl -X POST \
    -H "Content-Type: application/json" \
    -d @"./agent_workflow_identity_verification_evaluated.json" \
    ${API_BASE_URL}/api/subjects
rm -f "./agent_workflow_identity_verification_evaluated.json"

envsubst < "./agent_workflow_loan_decision.json" > "./agent_workflow_loan_decision_evaluated.json"
curl -X POST \
    -H "Content-Type: application/json" \
    -d @"./agent_workflow_loan_decision_evaluated.json" \
    ${API_BASE_URL}/api/subjects
rm -f "./agent_workflow_loan_decision_evaluated.json"

envsubst < "./agent_workflow_loan_risk_router.json" > "./agent_workflow_loan_risk_router_evaluated.json"
curl -X POST \
    -H "Content-Type: application/json" \
    -d @"./agent_workflow_loan_risk_router_evaluated.json" \
    ${API_BASE_URL}/api/subjects
rm -f "./agent_workflow_loan_risk_router_evaluated.json"

envsubst < "./agent_workflow_market_risk.json" > "./agent_workflow_market_risk_evaluated.json"
curl -X POST \
    -H "Content-Type: application/json" \
    -d @"./agent_workflow_market_risk_evaluated.json" \
    ${API_BASE_URL}/api/subjects
rm -f "./agent_workflow_market_risk_evaluated.json"

envsubst < "./agent_workflow_transaction_history.json" > "./agent_workflow_transaction_history_evaluated.json"
curl -X POST \
    -H "Content-Type: application/json" \
    -d @"./agent_workflow_transaction_history_evaluated.json" \
    ${API_BASE_URL}/api/subjects
rm -f "./agent_workflow_transaction_history_evaluated.json"
