#!/bin/bash

GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$GIT_ROOT" ]; then GIT_ROOT=$(pwd); fi
if [ -f "$GIT_ROOT/.env" ]; then set -a; source "$GIT_ROOT/.env"; set +a; else echo "Error: .env file MUST be present at $GIT_ROOT"; exit 1; fi

RESPONSE=$(curl -s "${API_BASE_URL}/api/runtime-workflows?workflow_uri=workflow-developer-team:1.0.0-production&limit=20&skip=0")
WORKFLOW_URL=$(echo "$RESPONSE" | python3 -c 'import sys, json; print(json.load(sys.stdin)["data"][0]["url"])' 2>/dev/null)

if [ -z "$WORKFLOW_URL" ]; then
    echo "Error: Could not retrieve workflow URL from response: $RESPONSE"
    exit 1
fi  

echo "Executing workflow at $WORKFLOW_URL"

# Shared variables
PROBLEM_STATEMENT='{\"product\": \"A new AI-driven smart coffee machine that adjusts brewing based on morning grogginess detected by face scan.\"}'
SESSION_ID="session-developer-demo-multistep-"$(( RANDOM % 100 ))
TASK_ID="task-developer-demo-multistep-"$(( RANDOM % 100 ))
USER_REQUEST="Develop the backend APIs and frontend React dashboard for the coffee machine"

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
echo "Sending Request 1 (estimate_budget):"
echo "$ESTIMATE_BUDGET_PAYLOAD"
curl -X POST "$WORKFLOW_URL/api/execute" -H "Content-Type: application/json" -d "$ESTIMATE_BUDGET_PAYLOAD"
echo -e "\nRequest 1 executed.\n"

sleep 1

SESSION_ID="session-developer-demo-multistep-"$(( RANDOM % 100 ))
# --- Request 2: process_artifact (Architecture Blueprint) ---
ARCH_ARTIFACT_PAYLOAD=$(cat <<EOF
{
  "task_type": "process_artifact",
  "text": "$PROBLEM_STATEMENT",
  "problem_statement": {"product": "A new AI-driven smart coffee machine that adjusts brewing based on morning grogginess detected by face scan."},
  "artifact_data": {
    "team_name": "Arch & Design Team",
    "status": "success",
    "blueprint": "The system consists of a smart camera scanner frontend component that sends face scans to a grogginess classifier service. The service computes a grogginess score (1-10) and calls the brewing optimization service, which adjusts water temperature and flow rate."
  },
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
echo "Sending Request 2 (process_artifact - Architecture):"
echo "$ARCH_ARTIFACT_PAYLOAD"
curl -X POST "$WORKFLOW_URL/api/execute" -H "Content-Type: application/json" -d "$ARCH_ARTIFACT_PAYLOAD"
echo -e "\nRequest 2 executed.\n"

sleep 1

SESSION_ID="session-developer-demo-multistep-"$(( RANDOM % 100 ))
# --- Request 3: execute_task (Deliverables) ---
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
    "MinIO backend API files",
    "MinIO React frontend integration files",
    "Deployment configuration package"
  ]
}
EOF
)

echo "---------------------------------------------------"
echo "Sending Request 3 (execute_task - Trigger Deliverables):"
echo "$EXECUTE_TASK_PAYLOAD"
curl -X POST "$WORKFLOW_URL/api/execute" -H "Content-Type: application/json" -d "$EXECUTE_TASK_PAYLOAD"
echo -e "\nRequest 3 executed.\n"
