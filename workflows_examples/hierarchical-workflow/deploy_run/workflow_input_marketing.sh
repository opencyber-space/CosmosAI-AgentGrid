#!/bin/bash

GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$GIT_ROOT" ]; then GIT_ROOT=$(pwd); fi
if [ -f "$GIT_ROOT/.env" ]; then set -a; source "$GIT_ROOT/.env"; set +a; else echo "Error: .env file MUST be present at $GIT_ROOT"; exit 1; fi

RESPONSE=$(curl -s "${API_BASE_URL}/api/runtime-workflows?workflow_uri=workflow-marketing-team:1.0.0-production&limit=20&skip=0")
WORKFLOW_URL=$(echo "$RESPONSE" | python3 -c 'import sys, json; print(json.load(sys.stdin)["data"][0]["url"])' 2>/dev/null)

if [ -z "$WORKFLOW_URL" ]; then
    echo "Error: Could not retrieve workflow URL from response: $RESPONSE"
    exit 1
fi  

echo "Executing workflow at $WORKFLOW_URL"

# Common parameters extracted from agent_cos.py structure
PROBLEM_STATEMENT='{\"product\": \"A new AI-driven smart coffee machine that adjusts brewing based on morning grogginess detected by face scan.\"}'
SESSION_ID="session-marketing-demo-"$(( RANDOM % 100 ))
TASK_ID="task-marketing-demo-"$(( RANDOM % 100 ))
USER_REQUEST="Launch plan for the smart coffee machine"

# --- Request 1: estimate_budget ---
ESTIMATE_BUDGET_PAYLOAD=$(cat <<EOF
{
  "task_type": "estimate_budget",
  "text": "$PROBLEM_STATEMENT",
  "problem_statement": {"product": "A new AI-driven smart coffee machine that adjusts brewing based on morning grogginess detected by face scan."},
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
echo "Sending Request 1 (estimate_budget): $ESTIMATE_BUDGET_PAYLOAD"
curl -X POST "$WORKFLOW_URL/api/execute" -H "Content-Type: application/json" -d "$ESTIMATE_BUDGET_PAYLOAD"
echo -e "\nRequest 1 (estimate_budget) executed.\n"

sleep 2 # Small delay between requests to simulate workflow timing

# --- Request 2: execute_task ---
EXECUTE_TASK_PAYLOAD=$(cat <<EOF
{
  "task_type": "execute_task",
  "text": "$PROBLEM_STATEMENT",
  "problem_statement": {"product": "A new AI-driven smart coffee machine that adjusts brewing based on morning grogginess detected by face scan."},
  "session_id": "$SESSION_ID",
  "model_name": "openai:gpt-5.4-mini",
  "communication_type": "workflow",
  "task_id": "$TASK_ID",
  "user_request": "$USER_REQUEST",
  "priority": "Fast",
  "deliverables": [
    "Market Analysis",
    "Digital Ad Copy",
    "Landing Page Design",
    "Social Media Strategy"
  ]
}
EOF
)

echo "---------------------------------------------------"
echo "Sending Request 2 (execute_task): $EXECUTE_TASK_PAYLOAD"
curl -X POST "$WORKFLOW_URL/api/execute" -H "Content-Type: application/json" -d "$EXECUTE_TASK_PAYLOAD"
echo -e "\nRequest 2 (execute_task) executed.\n"
