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

set -euo pipefail

session_id="sess-$(printf "%05d" $((RANDOM % 100000)))"
echo "----------------------------------------------------------------"
echo "Starting Coding Task Triage Sequence"
echo "Using session_id: ${session_id}"
echo "----------------------------------------------------------------"

CUR_DIR=$(dirname "$(realpath "$0")")

# Note: The server IP/Port and Model Name are hardcoded for the demo environment.
SERVER_URL="${DELEGATE_API_URL}"
MODEL_NAME="aios:qwen3-1-7b-vllm-block"

run_triage() {
    local title=$1
    local text=$2
    
    echo ">>> Running Triage for: ${title}"
    echo ">>> INPUT:"
    echo "${text}"
    echo "----------------------------------------------------------------"

    # Generate payload
    python3 - <<PY >$CUR_DIR/payload.json
import os, json
payload = {
  "subject_id": "code-text-normalizer",
  "session_id": "${session_id}",
  "task_id": "task-$(printf "%03d" $((RANDOM % 1000)))",
  "task_data": {
    "text": """${text}""",
    "session_id": "${session_id}",
    "model_name": "${MODEL_NAME}",
    "communication_type": "p2p"
  }
}
print(json.dumps(payload))
PY

    # Send request and capture response
    RESPONSE=$(curl -s -X POST "${SERVER_URL}/api/submit-and-wait" \
      -H "Content-Type: application/json" \
      -d @$CUR_DIR/payload.json)

    # Check for success
    if echo "$RESPONSE" | jq -e '.status == "success"' > /dev/null; then
        echo ">>> OUTPUT (Final Triage Summary):"
        # The output is nested in job_output -> text as a JSON string
        FINAL_JSON=$(echo "$RESPONSE" | jq -r '.data.job_output.text')
        if [ "$FINAL_JSON" != "null" ]; then
            echo "$FINAL_JSON" | jq -r '.triage_summary_markdown'
            echo "----------------------------------------------------------------"
            echo "Quality Gaps identified:"
            echo "$FINAL_JSON" | jq -r '.quality_gaps[] | "- " + .'
        else
            echo "Error: Final output was null or malformed."
            echo "$RESPONSE" | jq .
        fi
    else
        echo "Error: Processing failed."
        echo "$RESPONSE" | jq .
    fi
    echo "================================================================"
}

# --- BUG CASE ---
BUG_TEXT="code:
# tool/export_csv.py
import csv

def export_csv(rows, path):
    f = open(path, \"w\")
    writer = csv.writer(f)
    for r in rows:
        writer.writerow(r)

if __name__ == \"__main__\":
    bad = [[b\"\xff\xfe\", \"x\"]]
    export_csv(bad, \"out.csv\")
    
note:
Identify and handle bug in this piece of code above."

run_triage "Bug Branch" "${BUG_TEXT}"

# --- FEATURE CASE ---
FEATURE_TEXT="code:
# tool/export_csv.py (current behavior)
def export_csv(rows, path, *, delimiter=\",\"):
    # Writes plain CSV with default delimiter only
    import csv
    with open(path, \"w\", newline=\"\") as f:
        writer = csv.writer(f, delimiter=delimiter)
        for r in rows:
            writer.writerow(r)
    
note:
Add gzip compression support to export_csv via a compress=True flag."

run_triage "Feature Branch" "${FEATURE_TEXT}"