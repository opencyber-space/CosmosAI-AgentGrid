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


#!/bin/bash

curl -X POST ${DIRECT_API_URL}/submitTask \
    -d '{"session_id": "sess-126", "message_data": {"task_id":"t1","job_data":{"text":"Meeting Goal: Finalize logistics for 50-person group trip. Attendees: Chris (Finance Dept), Sam (Transport Dept), Lee (Location Guide Agency).","model_name":"aios:qwen3-1-7b-vllm-block","session_id": "sess-126"}, "output_ptr": {"exchange_id": "central-exchange-001"}}}' \
    -H "Content-Type: application/json"