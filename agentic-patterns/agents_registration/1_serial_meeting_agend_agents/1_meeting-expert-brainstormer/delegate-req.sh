
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



#!/bin/bash

session_id="sess-$(printf "%05d" $((RANDOM % 100000)))"
echo "Using session_id: ${session_id}"

curl -X POST ${DELEGATE_API_URL}/api/submit-and-wait \
 -H "Content-Type: application/json" \
 -d "{

    \"subject_id\": \"meeting-topic-brainstormer\",

    \"session_id\": \"${session_id}\",

    \"task_id\": \"task-003\",

    \"task_data\": {\"text\":\"Meeting Goal: Finalize logistics for 50-person group trip. Attendees: Chris (Finance Dept), Sam (Transport Dept), Lee (Location Guide Agency).\",\"session_id\": \"${session_id}\",\"model_name\":\"aios:qwen3-1-7b-vllm-block\", \"communication_type\":\"p2p\"}
  }" | json_pp