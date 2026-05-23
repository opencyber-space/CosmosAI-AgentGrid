
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

session_id="sess-$(printf "%05d" $((RANDOM % 100000)))"
echo "Using session_id: ${session_id}"

RESPONSE=$(curl -s -X POST ${DELEGATE_API_URL}/api/submit-and-wait \
 -H "Content-Type: application/json" \
 -d "{
    \"subject_id\": \"router-agent\",
    \"session_id\": \"${session_id}\",
    \"task_id\": \"task-004\",
    \"task_data\": {\"text\":\"My internet keeps dropping, and your system overcharged me this month.\",\"session_id\": \"${session_id}\",\"model_name\":\"aios:qwen3-1-7b-vllm-block\", \"communication_type\":\"direct\"}
  }")

# Extract Input and Output
INPUT=$(echo "$RESPONSE" | jq -r '.ack.result.messages[0].message_data.job_data.text // "No Input Found"')
OUTPUT=$(echo "$RESPONSE" | jq -r '.output.job_output.text // "No Output Found"')

# Print colorized
echo -e "\033[0;34mINPUT:\033[0m"
echo -e "\033[0;34m$INPUT\033[0m"
echo ""
echo -e "\033[0;32mOUTPUT:\033[0m"
echo -e "\033[0;32m$OUTPUT\033[0m"