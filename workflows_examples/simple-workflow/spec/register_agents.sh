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


envsubst < "./agent_clause_extractor.json" > "./agent_clause_extractor_evaluated.json"
curl -X POST \
    -H "Content-Type: application/json" \
    -d @"./agent_clause_extractor_evaluated.json" \
    ${API_BASE_URL}/api/subjects
rm -f "./agent_clause_extractor_evaluated.json"

envsubst < "./agent_compliance_checker.json" > "./agent_compliance_checker_evaluated.json"
curl -X POST \
    -H "Content-Type: application/json" \
    -d @"./agent_compliance_checker_evaluated.json" \
    ${API_BASE_URL}/api/subjects
rm -f "./agent_compliance_checker_evaluated.json"

envsubst < "./agent_legal_memo.json" > "./agent_legal_memo_evaluated.json"
curl -X POST \
    -H "Content-Type: application/json" \
    -d @"./agent_legal_memo_evaluated.json" \
    ${API_BASE_URL}/api/subjects
rm -f "./agent_legal_memo_evaluated.json"

envsubst < "./agent_negotiation_advisor.json" > "./agent_negotiation_advisor_evaluated.json"
curl -X POST \
    -H "Content-Type: application/json" \
    -d @"./agent_negotiation_advisor_evaluated.json" \
    ${API_BASE_URL}/api/subjects
rm -f "./agent_negotiation_advisor_evaluated.json"

envsubst < "./agent_risk_identifier.json" > "./agent_risk_identifier_evaluated.json"
curl -X POST \
    -H "Content-Type: application/json" \
    -d @"./agent_risk_identifier_evaluated.json" \
    ${API_BASE_URL}/api/subjects
rm -f "./agent_risk_identifier_evaluated.json"