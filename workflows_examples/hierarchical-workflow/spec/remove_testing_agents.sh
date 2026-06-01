#!/bin/bash
GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$GIT_ROOT" ]; then GIT_ROOT=$(pwd); fi
if [ -f "$GIT_ROOT/.env" ]; then set -a; source "$GIT_ROOT/.env"; set +a; else echo "Error: .env file MUST be present at $GIT_ROOT"; exit 1; fi

TESTING_AGENTS=(
  "agent-workflow-testing-team-lead"
  "agent-workflow-testing-dev"
)

echo "Removing all 2 Testing Workflow Agent deployments..."

for agent in "${TESTING_AGENTS[@]}"; do
    echo "Removing deployment for: ${agent}"
    curl -s -X POST "${API_BASE_URL}/api/remove-agent/deployer-123/${agent}"
    echo ""
done

echo "Testing Workflow Agent deployments removed."
