#!/bin/bash

GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$GIT_ROOT" ]; then GIT_ROOT=$(pwd); fi
if [ -f "$GIT_ROOT/.env" ]; then set -a; source "$GIT_ROOT/.env"; set +a; else echo "Error: .env file MUST be present at $GIT_ROOT"; exit 1; fi

RESPONSE=$(curl -s "${API_BASE_URL}/api/runtime-workflows?workflow_uri=workflow-financial-team:1.0.0-production&limit=20&skip=0")
WORKFLOW_URL=$(echo "$RESPONSE" | python3 -c 'import sys, json; print(json.load(sys.stdin)["data"][0]["url"])' 2>/dev/null)

if [ -z "$WORKFLOW_URL" ]; then
    echo "Error: Could not retrieve workflow URL from response: $RESPONSE"
    exit 1
fi  

echo "Executing workflow at $WORKFLOW_URL"

SESSION_ID="session-financial-demo"
TASK_ID="task-financial-demo-1"
USER_REQUEST="I need a marketing budget for the smart coffee machine"

# CoS passes an AggregatedBudget object for approve_budget
BUDGET_PAYLOAD=$(cat <<EOF
{
  "estimates": [
    {
      "team_name": "Marketing Team",
      "amount": 50000,
      "deliverables": ["Social Ads", "Landing Page"]
    }
  ],
  "buffer": 5000,
  "total": 55000
}
EOF
)
# Ensure to escape quotes for the json text property
BUDGET_PAYLOAD_ESCAPED=$(echo "$BUDGET_PAYLOAD" | jq -R -s -c '.')

# --- Request 1: approve_budget ---
# CoS delegates to financial team lead
APPROVE_BUDGET_JSON=$(cat <<EOF
{
  "task_type": "approve_budget",
  "text": $BUDGET_PAYLOAD_ESCAPED,
  "session_id": "$SESSION_ID",
  "model_name": "openai:gpt-5.4-mini",
  "communication_type": "workflow",
  "task_id": "$TASK_ID",
  "user_request": "$USER_REQUEST",
  "priority": "Fast"
}
EOF
)

echo "---------------------------------------------------"
echo "Sending Request 1 (approve_budget)"
curl -X POST "$WORKFLOW_URL/api/execute" -H "Content-Type: application/json" -d "$APPROVE_BUDGET_JSON"
echo -e "\nRequest 1 executed.\n"

sleep 2

PROBLEM_STATEMENT='{\"product\": \"A new AI-driven smart coffee machine that adjusts brewing based on morning grogginess detected by face scan.\"}'

# --- Request 2: execute_task ---
# execute_task in financial team translates to an audit request
EXECUTE_TASK_JSON=$(cat <<EOF
{
  "task_type": "execute_task",
  "text": "$PROBLEM_STATEMENT",
  "session_id": "$SESSION_ID",
  "model_name": "openai:gpt-5.4-mini",
  "communication_type": "workflow",
  "task_id": "$TASK_ID",
  "user_request": "$USER_REQUEST",
  "priority": "Fast",
  "deliverables": []
}
EOF
)

echo "---------------------------------------------------"
echo "Sending Request 2 (execute_task)"
curl -X POST "$WORKFLOW_URL/api/execute" -H "Content-Type: application/json" -d "$EXECUTE_TASK_JSON"
echo -e "\nRequest 2 executed.\n"
