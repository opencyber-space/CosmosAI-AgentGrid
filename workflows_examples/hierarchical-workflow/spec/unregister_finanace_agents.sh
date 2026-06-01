#!/bin/bash
GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$GIT_ROOT" ]; then GIT_ROOT=$(pwd); fi
if [ -f "$GIT_ROOT/.env" ]; then set -a; source "$GIT_ROOT/.env"; set +a; else echo "Error: .env file MUST be present at $GIT_ROOT"; exit 1; fi

FINANCE_AGENTS=(
  "agent-workflow-financial-team-lead"
  "agent-workflow-financial-accountant"
  "agent-workflow-financial-strategist"
  "agent-workflow-financial-controller"
)

echo "Unregistering all 4 Finance Workflow Agents..."

for agent in "${FINANCE_AGENTS[@]}"; do
    echo "Unregistering Agent: ${agent}"
    curl -s -X DELETE "${API_BASE_URL}/api/subjects/${agent}"
    echo ""
done

echo "Finance Workflow Agents unregistered successfully."
