#!/bin/bash

# Smoke-calls the static functions through the registry, the same way OpenArcade will.
# Usage: ./call.sh [va-bidding-pqt|va-bid-eval|all]

GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$GIT_ROOT" ]; then
    GIT_ROOT=$(pwd)
fi
if [ -f "$GIT_ROOT/.env" ]; then
    set -a; source "$GIT_ROOT/.env"; set +a
else
    echo "Error: .env file MUST be present at $GIT_ROOT"
    exit 1
fi

API="${FUNCTION_REGISTRY_URL}"
TARGET="${1:-all}"

call_pqt() {
  echo "=== Calling va-bidding-pqt (expect accepted:false -- NewGenTech's credentials) ==="
  curl -sS -X POST "${API}/function/call_as_job/executor-001" \
    -H "Content-Type: application/json" \
    -d '{
      "function_id": "va-bidding-pqt:1.0-stable",
      "job_name": "eval-va-bidding-pqt-job",
      "parameters": {},
      "node_selector": {},
      "inputs": {
        "bid_job": {"bid_job_id": "smoke-job"},
        "bid": {
          "bid_id": "smoke-bid",
          "bid_subject_id": "newgentech-bid-manager",
          "bid_data": {
            "bid_status": "submitted",
            "credentials": {"certifications": [], "projects_served": 2, "licenses_supplied": 3500}
          }
        }
      }
    }' | jq || true
}

call_eval() {
  echo "=== Calling va-bid-eval (expect winner ultravideotech-bid-manager) ==="
  curl -sS -X POST "${API}/function/call_as_job/executor-001" \
    -H "Content-Type: application/json" \
    -d '{
      "function_id": "va-bid-eval:1.3-stable",
      "job_name": "eval-va-bid-eval-job",
      "parameters": {},
      "node_selector": {},
      "inputs": {
        "bid_job": {"bid_job_id": "smoke-job", "bid_job_metadata": {"evaluation": {"sample_images": []}}},
        "bids": [
          {"bid_subject_id": "camfacesolution-bid-manager",
           "bid_data": {"bid_status": "submitted", "company": "CamFaceSolution", "total_budget": 48500000,
                        "sizing": {"cpu_cores": 640, "ram_gb": 2560, "disk_gb": 92000, "gpu_count": 40},
                        "compliance": {"met": 15, "total": 20}, "live_endpoints": []}},
          {"bid_subject_id": "ultravideotech-bid-manager",
           "bid_data": {"bid_status": "submitted", "company": "UltraVideoTech", "total_budget": 52000000,
                        "sizing": {"cpu_cores": 520, "ram_gb": 2080, "disk_gb": 74000, "gpu_count": 28},
                        "compliance": {"met": 16, "total": 20}, "live_endpoints": []}},
          {"bid_subject_id": "multifacetech-bid-manager",
           "bid_data": {"bid_status": "declined", "company": "MultiFaceTech", "decline_reason": "indoor only"}}
        ]
      }
    }' | jq || true
}

case "$TARGET" in
  va-bidding-pqt) call_pqt ;;
  va-bid-eval)    call_eval ;;
  all)            call_pqt; echo ""; call_eval ;;
  *)
    echo "Unknown target: $TARGET"
    echo "Usage: $0 [va-bidding-pqt|va-bid-eval|all]"
    exit 1 ;;
esac
