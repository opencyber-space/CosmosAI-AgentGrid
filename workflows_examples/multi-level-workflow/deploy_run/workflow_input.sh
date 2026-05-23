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


# Fetch the workflow execution URL
RESPONSE=$(curl -s "${API_BASE_URL}/api/runtime-workflows?workflow_uri=workflow-loan-risk-assessment:1.0.0-production&limit=20&skip=0")
WORKFLOW_URL=$(echo "$RESPONSE" | python3 -c 'import sys, json; print(json.load(sys.stdin)["data"][0]["url"])')

if [ -z "$WORKFLOW_URL" ]; then
    echo "Error: Could not retrieve workflow URL from response: $RESPONSE"
    exit 1
fi  

echo "Executing workflow at $WORKFLOW_URL"


# echo "For Acceptance Testing:"
# INPUT_TEXT='Applicant: John Smith Loan amount requested: $850,000 Purpose: Commercial property purchase Annual income: $180,000 (self-employed, consulting) Credit score: 720 Total existing debt: $320,000 Collateral: Residential property valued at $1000K Employment: Self-employed for 3 years, previously unemployed for 2 years Recent activity: 3 large cash deposits totalling $95,000 in last 60 days'
# echo "$INPUT_TEXT"

# curl -X POST "$WORKFLOW_URL/api/execute" -H "Content-Type: application/json" \
# -d '{
#   "text": "'"$INPUT_TEXT"'"
# }'


echo "For Fraud Investigation Testing:"
INPUT_TEXT='Applicant: John Smith Loan amount requested: $1250,000 Purpose: Commercial property purchase Annual income: $180,000 (self-employed, consulting) Credit score: 480 Total existing debt: $320,000 Collateral: Residential property valued at $200K Employment: Self-employed for 3 years, previously unemployed for 2 years Recent activity: 3 large cash deposits totalling $95,000 in last 60 days'
echo "$INPUT_TEXT"

curl -X POST "$WORKFLOW_URL/api/execute" -H "Content-Type: application/json" \
-d '{
  "text": "'"$INPUT_TEXT"'"
}'