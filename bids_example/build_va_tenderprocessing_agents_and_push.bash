#!/bin/bash
set -euo pipefail

# Build and push the video analytics tender-processing agents.
#
#   ./build_va_tenderprocessing_agents_and_push.bash                    all 30
#   ./build_va_tenderprocessing_agents_and_push.bash CamFaceSolution    one company's 6
#   ./build_va_tenderprocessing_agents_and_push.bash managers           the 5 Bid Managers
#   ./build_va_tenderprocessing_agents_and_push.bash camfacesolution-head   one agent
#
# The image tag is the agent's subject_id, which is also the AGENT value entrypoint.sh
# dispatches on and the name the agent spec asks the deployer for. Those three have to
# agree or the pod starts the wrong module.

GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
[ -z "$GIT_ROOT" ] && GIT_ROOT=$(pwd)
if [ -f "$GIT_ROOT/.env" ]; then
    set -a; source "$GIT_ROOT/.env"; set +a
else
    echo "Error: .env file MUST be present at $GIT_ROOT" >&2; exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SLUGS=(camfacesolution multifacetech newgentech ultravideotech videoproctech)
ROLES=(bid-manager ai-compliance sizing finance bid-reviewer head)

all_agents() {
    for slug in "${SLUGS[@]}"; do
        for role in "${ROLES[@]}"; do echo "${slug}-${role}"; done
    done
}

TARGET="${1:-all}"
AGENTS=()

case "$(echo "$TARGET" | tr '[:upper:]' '[:lower:]')" in
  all)
    mapfile -t AGENTS < <(all_agents) ;;
  managers|bid_managers|bid-managers)
    for slug in "${SLUGS[@]}"; do AGENTS+=("${slug}-bid-manager"); done ;;
  subordinates|subs)
    for slug in "${SLUGS[@]}"; do
        for role in "${ROLES[@]}"; do
            [ "$role" = "bid-manager" ] && continue
            AGENTS+=("${slug}-${role}")
        done
    done ;;
  camfacesolution|multifacetech|newgentech|ultravideotech|videoproctech)
    slug=$(echo "$TARGET" | tr '[:upper:]' '[:lower:]')
    for role in "${ROLES[@]}"; do AGENTS+=("${slug}-${role}"); done ;;
  *)
    # A single agent, by subject_id. Checked against the real list rather than built
    # from the argument, so a typo fails here instead of producing an image that
    # entrypoint.sh has no case for and that starts nothing.
    if all_agents | grep -qx "$TARGET"; then
        AGENTS=("$TARGET")
    else
        echo "Error: unknown target '$TARGET'." >&2
        echo "" >&2
        echo "Usage: $0 [all|managers|subordinates|<Company>|<subject-id>]" >&2
        echo "" >&2
        echo "Companies: ${SLUGS[*]}" >&2
        echo "Roles:     ${ROLES[*]}" >&2
        exit 1
    fi ;;
esac

echo "========================================================================="
echo "Building ${#AGENTS[@]} video analytics agent image(s)  (target: ${TARGET})"
echo "Registry: ${DOCKER_REGISTRY}"
echo "========================================================================="

BUILT=0
for agent in "${AGENTS[@]}"; do
    echo ""
    echo "-------------------------------------------------------------------------"
    echo "Building ${agent}"
    echo "-------------------------------------------------------------------------"
    bash "${SCRIPT_DIR}/build_docker.bash" "${agent}"

    echo "Pushing ${DOCKER_REGISTRY}/${agent}:latest"
    docker push "${DOCKER_REGISTRY}/${agent}:latest"
    BUILT=$((BUILT+1))
    echo "Done: ${agent}  (${BUILT}/${#AGENTS[@]})"
done

echo ""
echo "========================================================================="
echo "Built and pushed ${BUILT} image(s)."
echo ""
echo "Next:"
echo "  bash video_analytics_bidding/spec/register.sh"
echo "  bash video_analytics_bidding/spec/register_subjects_in_Exchange.sh"
echo "  bash video_analytics_bidding/deploy_run/deploy.sh"
echo "========================================================================="
