
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

# Request 1: Task Management Dashboard (Kanban Style)
session_id_1="sess-taskmgr-$(printf "%05d" $((RANDOM % 100000)))"
echo "--- Request 1: Task Management Dashboard ---"
echo "Using session_id: ${session_id_1}"

RESPONSE_1=$(curl -s -X POST ${DELEGATE_API_URL}/api/submit-and-wait \
  -H "Content-Type: application/json" \
  -d "{
     \"subject_id\": \"company-ceo-agent\",
     \"session_id\": \"${session_id_1}\",
     \"task_id\": \"task-mgr-001\",
     \"task_data\": {
       \"text\": \"Develop a Task Management Dashboard (Kanban Style). \\n\\nFrontend: A dashboard featuring a task board with columns for To-Do, In Progress, and Done. Include forms for creating new projects and detailed task views.\\nBackend: APIs to support CRUD operations for projects and tasks, user authentication, and persistent data storage.\",
       \"session_id\": \"${session_id_1}\",
       \"model_name\": \"aios:qwen3-1-7b-vllm-block\",
       \"communication_type\": \"p2p\"
     }
   }")

echo "=================================================="
echo "INPUT 1:"
echo "$RESPONSE_1" | jq -r '.ack.result.messages[0].message_data.job_data.text'
echo "--------------------------------------------------"
echo "OUTPUT 1:"
echo "$RESPONSE_1" | jq -r '.output.job_output.text'
echo "=================================================="

echo ""
echo ""

# Request 2: Personal Finance Tracker
# session_id_2="sess-finance-$(printf "%05d" $((RANDOM % 100000)))"
# echo "--- Request 2: Personal Finance Tracker ---"
# echo "Using session_id: ${session_id_2}"

# RESPONSE_2=$(curl -s -X POST ${DELEGATE_API_URL}/api/submit-and-wait \
#   -H "Content-Type: application/json" \
#   -d "{
#      \"subject_id\": \"company-ceo-agent\",
#      \"session_id\": \"${session_id_2}\",
#      \"task_id\": \"task-finance-001\",
#      \"task_data\": {
#        \"text\": \"Develop a Personal Finance Tracker application. \\n\\nFrontend: A mobile-responsive user interface for logging daily expenses, featuring category tagging and spending visualization charts.\\nBackend: APIs for managing expense records, categorization logic, and data aggregation for financial statistics.\",
#        \"session_id\": \"${session_id_2}\",
#        \"model_name\": \"aios:qwen3-1-7b-vllm-block\",
#        \"communication_type\": \"p2p\"
#      }
#    }")

# echo "=================================================="
# echo "INPUT 2:"
# echo "$RESPONSE_2" | jq -r '.ack.result.messages[0].message_data.job_data.text'
# echo "--------------------------------------------------"
# echo "OUTPUT 2:"
# echo "$RESPONSE_2" | jq -r '.output.job_output.text'
# echo "=================================================="
