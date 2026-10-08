#!/bin/bash
# Deploy the 30 agent pods (6 roles x 5 companies).
#
#   ./deploy.sh                              all 30
#   ./deploy.sh CamFaceSolution              one company's 6
#   ./deploy.sh CamFaceSolution bid_manager  one agent
#
# Pods reaching Running is NOT the same as being ready: an agent has to join the NATS
# mesh before it can receive a bid_request, and a Bid Manager that misses its request
# never bids -- which stalls the round permanently, because evaluation waits on every
# participant and has no timeout. Wait for the mesh join before submitting a task.

GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
[ -z "$GIT_ROOT" ] && GIT_ROOT=$(pwd)
if [ -f "$GIT_ROOT/.env" ]; then
    set -a; source "$GIT_ROOT/.env"; set +a
else
    echo "Error: .env file MUST be present at $GIT_ROOT" >&2; exit 1
fi

SPEC_DIR="$GIT_ROOT/bids_example/video_analytics_bidding/spec"
COMPANIES=(CamFaceSolution MultiFaceTech NewGenTech UltraVideoTech VideoProcTech)
ROLES=(bid_manager ai_compliance sizing finance bid_reviewer head)

TARGET_COMPANY="$1"
TARGET_ROLE="$2"
DEPLOYED=0

deploy_one() {
    local company="$1" role="$2"
    local spec_file="$SPEC_DIR/${company}/${role}.json"
    if [ ! -f "$spec_file" ]; then
        echo "  ! spec not found: $spec_file" >&2; return 1
    fi
    local subject_id
    subject_id=$(jq -r '.identity.subject_id' "$spec_file")
    echo "  ---> ${subject_id}"
    curl -s -X POST "${API_BASE_URL}/api/deploy-agent/deployer-123" \
        -H "Content-Type: application/json" \
        -d @- <<EOF > /dev/null
{
  "subject_id": "${subject_id}",
  "allocation": {
    "delegate_api_url": "${DELEGATE_API_URL}",
    "instances": [
      {
        "instance_id": "i1",
        "subject_id": "${subject_id}"
      }
    ],
    "meshes": [
      {
        "mesh_id": "mesh-a",
        "url": "${NATS_URL}"
      }
    ]
  }
}
EOF
    DEPLOYED=$((DEPLOYED+1))
}

echo "=========================================================="
echo "Deploying video analytics bidding agents"
echo "=========================================================="
for company in "${COMPANIES[@]}"; do
    [ -n "$TARGET_COMPANY" ] && [ "$company" != "$TARGET_COMPANY" ] && continue
    echo ""; echo "${company}:"
    for role in "${ROLES[@]}"; do
        [ -n "$TARGET_ROLE" ] && [ "$role" != "$TARGET_ROLE" ] && continue
        deploy_one "$company" "$role"
    done
done

# The exchange's subject records have been observed to be empty after a redeploy, and
# an empty exchange is silent about it: the topic query simply matches nobody, the task
# resolves to the three companies it names, and the round looks complete while the whole
# point of the example -- two companies joining on a topic -- goes undemonstrated.
# Re-registering here is idempotent and costs one call per company.
if [ -z "$TARGET_COMPANY" ] && [ -z "$TARGET_ROLE" ]; then
    echo ""
    echo "=========================================================="
    echo "Re-registering exchange subjects"
    echo "=========================================================="
    bash "$(realpath "$(dirname "$0")/../spec")/register_subjects_in_Exchange.sh" || {
        echo "" >&2
        echo "WARNING: the Bid Managers are not registered as exchange subjects." >&2
        echo "A round will resolve to the three companies named in the task and the two" >&2
        echo "topic listeners will be silently absent." >&2
    }
fi

echo ""
echo "Requested deployment of ${DEPLOYED} agent(s)."
echo ""
echo "Check readiness before submitting a task:"
echo "  \$KUBECTL_COMMAND get pods -n agents | grep -E 'camface|multiface|newgen|ultravideo|videoproc'"
echo "Wait for each pod to join the mesh, not merely to reach Running."
