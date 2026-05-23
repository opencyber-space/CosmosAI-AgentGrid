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
    if echo "$RESPONSE" | jq -e '.success == true' > /dev/null; then
        echo ">>> OUTPUT (Final Triage Summary):"
        # The output is deeply nested. We look for the text field containing our expected final fields.
        RAW_TEXT=$(echo "$RESPONSE" | jq -r '.. | .text? | select(. != null and contains("one_line_summary"))' | head -n 1)
        
        # Robustly strip DSPy markers using python to handle multi-line strings
        # We split on '[[ ##' which is the specific pattern for DSPy markers,
        # avoiding truncation on valid content like '[[b"\xff"]]'.
        FINAL_JSON=$(python3 -c "import sys; t=sys.stdin.read(); print(t.split('[[ ##')[0].strip())" <<EOF
$RAW_TEXT
EOF
)

        if [ -n "$FINAL_JSON" ] && echo "$FINAL_JSON" | jq . >/dev/null 2>&1; then
            TITLE=$(echo "$FINAL_JSON" | jq -r '.title // "N/A"')
            SUMMARY=$(echo "$FINAL_JSON" | jq -r '.one_line_summary // "N/A"')
            BODY=$(echo "$FINAL_JSON" | jq -r '.body_markdown // "N/A"')
            CODE=$(echo "$FINAL_JSON" | jq -r '.final_code // "None"')
            
            echo "Title: $TITLE"
            echo "Summary: $SUMMARY"
            echo "----------------------------------------------------------------"
            echo "$BODY"
            echo "----------------------------------------------------------------"
            if [ "$CODE" != "None" ] && [ -n "$CODE" ]; then
                echo ">>> FINAL CORRECTED/IMPROVED CODE:"
                echo "$CODE"
                echo "----------------------------------------------------------------"
            fi
            echo "Quality Flags identified:"
            # Check if quality_flags exists and is an array
            if echo "$FINAL_JSON" | jq -e '.quality_flags | type == "array"' >/dev/null 2>&1; then
                echo "$FINAL_JSON" | jq -r '.quality_flags[] | "- " + .'
            else
                echo "- None"
            fi
        else
            echo "Error: Final output was null, malformed, or unfinished."
            echo ">>> RAW TEXT RECEIVED:"
            echo "$RAW_TEXT" | head -n 20
            echo "... (truncated)"
        fi
    else
        echo "Error: Processing failed."
        echo "$RESPONSE" | jq .
    fi
    echo "================================================================"
}

# --- BUG CASE ---
# BUG_TEXT="code:
# # tool/export_csv.py
# import csv

# def export_csv(rows, path):
#     f = open(path, \"w\")
#     writer = csv.writer(f)
#     for r in rows:
#         writer.writerow(r)

# if __name__ == \"__main__\":
#     bad = [[b\"\xff\xfe\", \"x\"]]
#     export_csv(bad, \"out.csv\")
    
# note:
# Identify and handle bug in this piece of code above."

# run_triage "Bug Branch" "${BUG_TEXT}"

#--- FEATURE CASE ---
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