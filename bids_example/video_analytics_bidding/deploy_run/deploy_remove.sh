#!/bin/bash
# Remove the 30 agent deployments.
#
#   ./deploy_remove.sh                              all 30
#   ./deploy_remove.sh CamFaceSolution              one company's 6
#   ./deploy_remove.sh CamFaceSolution bid_manager  one agent
#
# Idempotent: removing an agent that is not deployed is not an error.

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
REMOVED=0

remove_one() {
    local company="$1" role="$2"
    local spec_file="$SPEC_DIR/${company}/${role}.json"
    [ -f "$spec_file" ] || return 0
    local subject_id
    subject_id=$(jq -r '.identity.subject_id' "$spec_file")
    echo "  ---> ${subject_id}"
    curl -s -X POST "${API_BASE_URL}/api/remove-agent/deployer-123/${subject_id}" \
        -H "Content-Type: application/json" > /dev/null
    REMOVED=$((REMOVED+1))
}

echo "=========================================================="
echo "Removing video analytics bidding agent deployments"
echo "=========================================================="
for company in "${COMPANIES[@]}"; do
    [ -n "$TARGET_COMPANY" ] && [ "$company" != "$TARGET_COMPANY" ] && continue
    echo ""; echo "${company}:"
    for role in "${ROLES[@]}"; do
        [ -n "$TARGET_ROLE" ] && [ "$role" != "$TARGET_ROLE" ] && continue
        remove_one "$company" "$role"
    done
done

echo ""
echo "Requested removal of ${REMOVED} agent(s)."
