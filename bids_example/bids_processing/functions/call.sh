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

API="${FUNCTION_REGISTRY_URL}"
TARGET="${1:-all}"

# ---------------------------------------------------------------------------
# 1. dummy-pqt
# ---------------------------------------------------------------------------
call_dummy_pqt() {
  echo "=== Calling dummy-pqt ==="
  PAYLOAD='{
    "function_id": "dummy-pqt:1.0-stable",
    "job_name": "eval-dummy-pqt-job",
    "parameters": {},
    "node_selector": {},
    "inputs": {
      "bid_job": {"bid_job_id": "test_job"},
      "bid": {"bid_id": "test_bid"}
    }
  }'
  curl -sS -X POST "${API}/function/call_as_job/executor-001" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD"
}

# ---------------------------------------------------------------------------
# 2. bids-evaluator
# ---------------------------------------------------------------------------
call_bids_evaluator() {
  echo "=== Calling bids-evaluator ==="
  PAYLOAD='{
    "function_id": "bids-evaluator:1.0-stable",
    "job_name": "eval-bids-evaluator-job",
    "parameters": {},
    "node_selector": {},
    "inputs": {
      "bid_job": {"bid_job_id": "test_job"},
      "bids": [
          {
              "bid_subject_id": "agent-1",
              "bid_data": {"total_estimated_tokens": 100, "required_compute": 50}
          },
          {
              "bid_subject_id": "agent-2",
              "bid_data": {"total_estimated_tokens": 80, "required_compute": 40}
          },
          {
              "bid_subject_id": "agent-3",
              "bid_data": {"total_estimated_tokens": 120, "required_compute": 60}
          }
      ]
    }
  }'
  curl -sS -X POST "${API}/function/call_as_job/executor-001" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD"
}

case "$TARGET" in
  dummy-pqt)       call_dummy_pqt ;;
  bids-evaluator)  call_bids_evaluator ;;
  all)
    call_dummy_pqt
    echo ""
    call_bids_evaluator
    ;;
  *)
    echo "Unknown target: $TARGET"
    echo "Usage: $0 [dummy-pqt|bids-evaluator|all]"
    exit 1
    ;;
esac
