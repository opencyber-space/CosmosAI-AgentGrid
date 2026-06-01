#!/bin/bash
GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$GIT_ROOT" ]; then GIT_ROOT=$(pwd); fi
if [ -f "$GIT_ROOT/.env" ]; then set -a; source "$GIT_ROOT/.env"; set +a; else echo "Error: .env file MUST be present at $GIT_ROOT"; exit 1; fi

MARKETING_AGENTS=(
  "agent-workflow-marketing-team-lead"
  "agent-workflow-marketing-strategy"
  "agent-workflow-marketing-planning"
  "agent-workflow-marketing-content"
  "agent-workflow-marketing-visual"
)

echo "Unregistering all 5 Marketing Workflow Agents..."

for agent in "${MARKETING_AGENTS[@]}"; do
    echo "Unregistering Agent: ${agent}"
    curl -s -X DELETE "${API_BASE_URL}/api/subjects/${agent}"
    echo ""
done

echo "Marketing Workflow Agents unregistered successfully."
