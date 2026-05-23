
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
    \"subject_id\": \"marketing-orchestrator-agent\",
    \"session_id\": \"${session_id}\",
    \"task_id\": \"task-005\",
    \"task_data\": {\"text\":\"A minimalist, eco-friendly bamboo electric toothbrush for Japan, Germany, Brazil\",\"session_id\": \"${session_id}\",\"model_name\":\"aios:qwen3-1-7b-vllm-block\", \"communication_type\":\"p2p\"}
  }")

echo "=================================================="
echo "INPUT:"
echo "$RESPONSE" | jq -r '.ack.result.messages[0].message_data.job_data.text'

echo "=================================================="
echo "OUTPUT:"
# The output.job_output.text is a string containing JSON, so we parse it twice: 
# once to get the string, and once to parse that string into JSON.
echo "$RESPONSE" | jq -r '.output.job_output.text' | sed 's|http://${INTERNAL_IP}|http://${EXTERNAL_IP}|g' | jq .
echo "=================================================="

#Germany, Brazil
