#!/bin/bash
GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$GIT_ROOT" ]; then GIT_ROOT=$(pwd); fi
if [ -f "$GIT_ROOT/.env" ]; then set -a; source "$GIT_ROOT/.env"; set +a; else echo "Error: .env file MUST be present at $GIT_ROOT"; exit 1; fi

ARCH_AGENTS=(
  "agent-workflow-arch-design-team-lead"
  "agent-workflow-arch-junior"
  "agent-workflow-arch-senior"
)

echo "Unregistering all 3 Architecture Workflow Agents..."

for agent in "${ARCH_AGENTS[@]}"; do
    echo "Unregistering Agent: ${agent}"
    curl -s -X DELETE "${API_BASE_URL}/api/subjects/${agent}"
    echo ""
done

echo "Architecture Workflow Agents unregistered successfully."
