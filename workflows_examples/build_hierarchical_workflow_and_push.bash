#!/bin/bash
set -euo pipefail

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

# Read optional parameter (defaults to all)
TARGET_FILTER="${1:-all}"

case "$TARGET_FILTER" in
  ceo)
    HIERARCHICAL_AGENTS=(
      "agent-workflow-ceo"
    )
    ;;
  cos)
    HIERARCHICAL_AGENTS=(
      "agent-workflow-cos"
    )
    ;;
  financial|finance|fin)
    HIERARCHICAL_AGENTS=(
      "agent-workflow-financial-team-lead"
      "agent-workflow-financial-accountant"
      "agent-workflow-financial-controller"
      "agent-workflow-financial-strategist"
    )
    ;;
  marketing|mark|sales)
    HIERARCHICAL_AGENTS=(
      "agent-workflow-marketing-team-lead"
      "agent-workflow-marketing-content"
      "agent-workflow-marketing-planning"
      "agent-workflow-marketing-strategy"
      "agent-workflow-marketing-visual"
    )
    ;;
  test|testing|qa)
    HIERARCHICAL_AGENTS=(
      "agent-workflow-testing-team-lead"
      "agent-workflow-testing-dev"
    )
    ;;
  dev|developer)
    HIERARCHICAL_AGENTS=(
      "agent-workflow-developer-team-lead"
      "agent-workflow-dev-backend"
      "agent-workflow-dev-frontend"
    )
    ;;
  architecture|arch)
    HIERARCHICAL_AGENTS=(
      "agent-workflow-arch-design-team-lead"
      "agent-workflow-arch-junior"
      "agent-workflow-arch-senior"
    )
    ;;
  all)
    HIERARCHICAL_AGENTS=(
      "agent-workflow-ceo"
      "agent-workflow-cos"
      "agent-workflow-financial-team-lead"
      "agent-workflow-financial-accountant"
      "agent-workflow-financial-controller"
      "agent-workflow-financial-strategist"
      "agent-workflow-marketing-team-lead"
      "agent-workflow-marketing-content"
      "agent-workflow-marketing-planning"
      "agent-workflow-marketing-strategy"
      "agent-workflow-marketing-visual"
      "agent-workflow-testing-team-lead"
      "agent-workflow-testing-dev"
      "agent-workflow-developer-team-lead"
      "agent-workflow-dev-backend"
      "agent-workflow-dev-frontend"
      "agent-workflow-arch-design-team-lead"
      "agent-workflow-arch-junior"
      "agent-workflow-arch-senior"
    )
    ;;
  *)
    echo "Error: Unknown filter option '$TARGET_FILTER'."
    echo "Usage: $0 [architecture|dev|test|marketing|financial|cos|ceo]"
    exit 1
    ;;
esac

echo "Starting Docker builds and pushes for ${#HIERARCHICAL_AGENTS[@]} agent(s) (Filter: ${TARGET_FILTER})..."

for agent in "${HIERARCHICAL_AGENTS[@]}"; do
    echo "========================================================================="
    echo "Building Agent: ${agent}"
    echo "========================================================================="
    bash build_docker.bash "${agent}"
    
    echo "-------------------------------------------------------------------------"
    echo "Pushing Agent: ${agent} to ${DOCKER_REGISTRY}"
    echo "-------------------------------------------------------------------------"
    docker push "${DOCKER_REGISTRY}/${agent}:latest"
    echo "Successfully built and pushed ${agent}"
    echo ""
done

echo "Selected Hierarchical Workflow Agent(s) have been built and pushed successfully!"
