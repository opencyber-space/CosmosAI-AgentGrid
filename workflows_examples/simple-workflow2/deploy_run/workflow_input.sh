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
RESPONSE=$(curl -s "${API_BASE_URL}/api/runtime-workflows?workflow_uri=legal-contract-review-workflow-static-dynamic-static:1.0.0-stable&limit=20&skip=0")
WORKFLOW_URL=$(echo "$RESPONSE" | python3 -c 'import sys, json; print(json.load(sys.stdin)["data"][0]["url"])')

if [ -z "$WORKFLOW_URL" ]; then
    echo "Error: Could not retrieve workflow URL from response: $RESPONSE"
    exit 1
fi

echo "Executing workflow at $WORKFLOW_URL"

curl -X POST "$WORKFLOW_URL/api/execute" -H "Content-Type: application/json" \
-d '{
  "text": "Contract: SaaS Subscription Agreement between Acme Corp (vendor) and RetailCo (client). Key clauses: auto-renewal at 15% price increase, no SLA guarantees, data ownership ambiguous, termination requires 180-day notice, liability cap at $5,000 regardless of contract value ($2M/year). Jurisdiction: Delaware, USA."
}' | json_pp