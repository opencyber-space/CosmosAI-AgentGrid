
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

echo "For BUG BRANCH i.e Agent3"

```# tool/export_csv.py
import csv

def export_csv(rows, path):
    f = open(path, "w")
    writer = csv.writer(f)
    for r in rows:
        writer.writerow(r)


if __name__ == "__main__":
    bad = [[b"\xff\xfe", "x"]]
    export_csv(bad, "out.csv")
    
CSV export crashes on non‑UTF‑8 bytes and sometimes leaves the file handle open. Repro: run tool/export_csv.py with bad bytes; see traceback from csv writer. Expected: graceful failure or sanitized output. Actual: exception and partial out.csv. Environment: Ubuntu 22.04, Python 3.10. Impact: CI job fails intermittently.```

curl -X POST ${DELEGATE_API_URL}/api/submit-and-wait \
 -H "Content-Type: application/json" \
 -d "{

    \"subject_id\": \"code-text-normalizer\",

    \"session_id\": \"${session_id}\",

    \"task_id\": \"task-003\",

    \"task_data\": {\"text\":\"Meeting Goal: Finalize logistics for 50-person group trip. Attendees: Chris (Finance Dept), Sam (Transport Dept), Lee (Location Guide Agency).\",\"session_id\": \"${session_id}\",\"model_name\":\"aios:qwen3-1-7b-vllm-block\", \"communication_type\":\"p2p\"}
  }" | json_pp




echo "For FEATURE BRANCH i.e Agent9"