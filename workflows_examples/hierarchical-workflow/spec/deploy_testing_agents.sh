#!/bin/bash
GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$GIT_ROOT" ]; then GIT_ROOT=$(pwd); fi
if [ -f "$GIT_ROOT/.env" ]; then set -a; source "$GIT_ROOT/.env"; set +a; else echo "Error: .env file MUST be present at $GIT_ROOT"; exit 1; fi

TESTING_AGENTS=(
  "agent-workflow-testing-team-lead"
  "agent-workflow-testing-dev"
)

echo "Deploying all 2 Testing Workflow Agents..."

for agent in "${TESTING_AGENTS[@]}"; do
    echo "Deploying Agent: ${agent}"
    curl -s -X POST "${API_BASE_URL}/api/deploy-agent/deployer-123" \
      -H "Content-Type: application/json" \
      -d @- <<EOF
{
  "subject_id": "${agent}",
  "allocation": {
    "delegate_api_url": "${DELEGATE_API_URL}",
    "instances": [
      {
        "instance_id": "i1",
        "subject_id": "${agent}"
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
    echo ""
done

echo "Testing Workflow Agents deployed successfully."
