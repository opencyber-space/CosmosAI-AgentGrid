#!/bin/bash

GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$GIT_ROOT" ]; then GIT_ROOT=$(pwd); fi
if [ -f "$GIT_ROOT/.env" ]; then set -a; source "$GIT_ROOT/.env"; set +a; else echo "Error: .env file MUST be present at $GIT_ROOT"; exit 1; fi

RESPONSE=$(curl -s "${API_BASE_URL}/api/runtime-workflows?workflow_uri=workflow-software-company:1.0.0-production&limit=20&skip=0")
WORKFLOW_URL=$(echo "$RESPONSE" | python3 -c 'import sys, json; print(json.load(sys.stdin)["data"][0]["url"])' 2>/dev/null)

if [ -z "$WORKFLOW_URL" ]; then
    echo "Error: Could not retrieve workflow URL from response: $RESPONSE"
    exit 1
fi  

echo "Executing Software Company Master Workflow at $WORKFLOW_URL"

SESSION_ID="sess-taskmgr-$(printf "%05d" $((RANDOM % 100000)))"
TASK_ID="task-mgr-001"
RAW_IDEA="Develop a Task Management Dashboard (Kanban Style). \n\nFrontend: A dashboard featuring a task board with columns for To-Do, In Progress, and Done. Include forms for creating new projects and detailed task views.\nBackend: APIs to support CRUD operations for projects and tasks, user authentication, and persistent data storage."

# Trigger Payload starting at the CEO root node
TRIGGER_PAYLOAD=$(cat <<EOF
{
  "text": "$RAW_IDEA",
  "session_id": "$SESSION_ID",
  "task_id": "$TASK_ID",
  "user_request": "$RAW_IDEA",
  "model_name": "openai:gpt-5.4-mini",
  "communication_type": "workflow"
}
EOF
)

echo "---------------------------------------------------"
echo "Sending Request to CEO Root Node:"
echo "$TRIGGER_PAYLOAD"
curl -X POST "$WORKFLOW_URL/api/execute" -H "Content-Type: application/json" -d "$TRIGGER_PAYLOAD"
echo -e "\nMaster workflow execution requested.\n"
