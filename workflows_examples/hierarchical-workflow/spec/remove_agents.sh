#!/bin/bash
GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$GIT_ROOT" ]; then GIT_ROOT=$(pwd); fi
if [ -f "$GIT_ROOT/.env" ]; then set -a; source "$GIT_ROOT/.env"; set +a; else echo "Error: .env file MUST be present at $GIT_ROOT"; exit 1; fi

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

echo "Removing all 19 Hierarchical Workflow Agent deployments..."

for agent in "${HIERARCHICAL_AGENTS[@]}"; do
    echo "Removing deployment for: ${agent}"
    curl -s -X POST "${API_BASE_URL}/api/remove-agent/deployer-123/${agent}"
    echo ""
done

echo "All 19 Hierarchical Workflow Agent deployments removed."
