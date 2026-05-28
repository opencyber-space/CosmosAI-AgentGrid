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


# Dynamically generate a session ID
session_id="sess-$(printf "%05d" $((RANDOM % 100000)))"
echo "Using session_id: ${session_id}"

# Submit the task and wait for the response
# Using -s for silent mode and -S to show errors
RESPONSE=$(curl -s -S -X POST ${DELEGATE_API_URL}/api/submit-and-wait \
 -H "Content-Type: application/json" \
 -d "{
    \"subject_id\": \"meeting-topic-brainstormer\",
    \"session_id\": \"${session_id}\",
    \"task_id\": \"task-003\",
    \"task_data\": {
      \"text\": \"Meeting Goal of 2 hour: Finalize logistics for 50-person group trip. Attendees: Chris (Finance Dept), Sam (Transport Dept), Lee (Location Guide Agency).\",
      \"session_id\": \"${session_id}\",
      \"model_name\": \"openai:gpt-5.4-mini\",
      \"communication_type\": \"p2p\"
    }
  }")

# Print Input and Output in a clean format
echo "=================================================="
echo "INPUT:"
# The original input goal from the request
echo "$RESPONSE" | jq -r '.ack.result.messages[0].message_data.job_data.text // .input_data.text'

echo "=================================================="
echo "OUTPUT:"
# Extract the last "text" field found in the output block
echo "$RESPONSE" | jq -r '.output | [.. | .text? | strings] | last // "null (no output found)"'
echo "=================================================="