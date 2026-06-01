#!/bin/bash
GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$GIT_ROOT" ]; then GIT_ROOT=$(pwd); fi
if [ -f "$GIT_ROOT/.env" ]; then set -a; source "$GIT_ROOT/.env"; set +a; else echo "Error: .env file MUST be present at $GIT_ROOT"; exit 1; fi

DEVELOPER_AGENTS=(
  "agent-workflow-developer-team-lead"
  "agent-workflow-dev-frontend"
  "agent-workflow-dev-backend"
)

echo "Removing all 3 Developer Workflow Agent deployments..."

for agent in "${DEVELOPER_AGENTS[@]}"; do
    echo "Removing deployment for: ${agent}"
    curl -s -X POST "${API_BASE_URL}/api/remove-agent/deployer-123/${agent}"
    echo ""
done

echo "Developer Workflow Agent deployments removed."
