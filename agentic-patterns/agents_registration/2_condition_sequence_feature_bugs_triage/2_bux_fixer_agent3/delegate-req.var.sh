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
echo "Using session_id: ${session_id}"

CUR_DIR=$(dirname "$(realpath "$0")")

echo "For BUG BRANCH i.e Agent3"
# The block below (previously embedded between ``` and ```) is stored in a variable
# so it can be injected into the JSON task_data.text field safely with proper escaping.
# TEXT=$(cat <<'TEXT'
# code:
# # tool/export_csv.py
# import csv

# def export_csv(rows, path):
#     f = open(path, "w")
#     writer = csv.writer(f)
#     for r in rows:
#         writer.writerow(r)


# if __name__ == "__main__":
#     bad = [[b"\xff\xfe", "x"]]
#     export_csv(bad, "out.csv")
    
# note:
# CSV export crashes on non‑UTF‑8 bytes and sometimes leaves the file handle open. Repro: run tool/export_csv.py with bad bytes; see traceback from csv writer. Expected: graceful failure or sanitized output. Actual: exception and partial out.csv. Environment: Ubuntu 22.04, Python 3.10. Impact: CI job fails intermittently.
# TEXT

# export TEXT
# export SESSION_ID="${session_id}"

# # Build the JSON payload using Python to ensure the multi-line TEXT is escaped correctly
# python3 - <<'PY' | curl -s -X POST ${DELEGATE_API_URL}/api/submit-and-wait -H "Content-Type: application/json" -d @- | json_pp
# import os, json
# payload = {
#     "subject_id": "code-text-normalizer",
#     "session_id": os.environ.get("SESSION_ID"),
#     "task_id": "task-003",
#     "task_data": {
#         "text": os.environ.get("TEXT"),
#         "session_id": os.environ.get("SESSION_ID"),
#         "model_name": "aios:qwen3-1-7b-vllm-block",
#         "communication_type": "p2p"
#     }
# }
# print(json.dumps(payload))
# PY

# generate payload to inspect
SESSION_ID=$session_id TEXT="$(cat <<'E'
code:
# tool/export_csv.py
import csv

def export_csv(rows, path):
    f = open(path, "w")
    writer = csv.writer(f)
    for r in rows:
        writer.writerow(r)


if __name__ == "__main__":
    bad = [[b"\xff\xfe", "x"]]
    export_csv(bad, "out.csv")
    
note:
CSV export crashes on non‑UTF‑8 bytes and sometimes leaves the file handle open. Repro: run tool/export_csv.py with bad bytes; see traceback from csv writer. Expected: graceful failure or sanitized output. Actual: exception and partial out.csv. Environment: Ubuntu 22.04, Python 3.10. Impact: CI job fails intermittently.
E
)" python3 - <<'PY' >$CUR_DIR/payload.json
import os, json
payload = {
  "subject_id": "code-text-normalizer",
  "session_id": os.environ.get("SESSION_ID"),
  "task_id": "task-003",
  "task_data": {
    "text": os.environ.get("TEXT"),
    "session_id": os.environ.get("SESSION_ID"),
    "model_name": "aios:qwen3-1-7b-vllm-block",
    "communication_type": "p2p"
  }
}
print(json.dumps(payload))
PY

# inspect
jq . $CUR_DIR/payload.json

# send verbosely
curl -v -X POST ${DELEGATE_API_URL}/api/submit-and-wait \
  -H "Content-Type: application/json" \
  -d @$CUR_DIR/payload.json | jq .

# echo "For FEATURE BRANCH i.e Agent9"

# read -r -d '' TEXT <<'TEXT'
# code:
# # tool/export_csv.py (current behavior)
# def export_csv(rows, path, *, delimiter=","):
#     # Writes plain CSV with default delimiter only
#     import csv
#     with open(path, "w", newline="") as f:
#         writer = csv.writer(f, delimiter=delimiter)
#         for r in rows:
#             writer.writerow(r)
# note:
# Add gzip compression support to export_csv via a compress=True flag and optional compress_level (1–9). Default remains uncompressed for backward compatibility. Acceptance: when compress=True, writes path+'.gz' using gzip, preserves CSV formatting and schema, and round‑trip load passes in tests.
# TEXT

# export TEXT
# export SESSION_ID="${session_id}"

# # Build the JSON payload using Python to ensure the multi-line TEXT is escaped correctly
# python3 - <<'PY' | curl -s -X POST ${DELEGATE_API_URL}/api/submit-and-wait -H "Content-Type: application/json" -d @- | json_pp
# import os, json
# payload = {
#     "subject_id": "code-text-normalizer",
#     "session_id": os.environ.get("SESSION_ID"),
#     "task_id": "task-003",
#     "task_data": {
#         "text": os.environ.get("TEXT"),
#         "session_id": os.environ.get("SESSION_ID"),
#         "model_name": "aios:qwen3-1-7b-vllm-block",
#         "communication_type": "p2p"
#     }
# }
# print(json.dumps(payload))
# PY