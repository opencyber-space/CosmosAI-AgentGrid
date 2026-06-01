#!/bin/bash
GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$GIT_ROOT" ]; then GIT_ROOT=$(pwd); fi
if [ -f "$GIT_ROOT/.env" ]; then set -a; source "$GIT_ROOT/.env"; set +a; else echo "Error: .env file MUST be present at $GIT_ROOT"; exit 1; fi

DEPLOY_RUN_DIR="$GIT_ROOT/workflows_examples/hierarchical-workflow/deploy_run"

echo "Deploying all 5 nested sub-workflows..."

for spec_file in "$DEPLOY_RUN_DIR"/workflow_spec-*.json; do
    echo "Deploying: $(basename "$spec_file")"
    curl -s -X POST "${API_BASE_URL}/api/workflows" \
      -H "Content-Type: application/json" \
      -d @"$spec_file"
    echo ""
done

echo "Deploying the Chief of Staff Sub-Workflow (workflow-cos.json)..."
curl -s -X POST "${API_BASE_URL}/api/workflows" \
  -H "Content-Type: application/json" \
  -d @"$DEPLOY_RUN_DIR/workflow-cos.json"
echo ""

echo "Deploying the Master Workflow (workflow-final.json)..."
curl -s -X POST "${API_BASE_URL}/api/workflows" \
  -H "Content-Type: application/json" \
  -d @"$DEPLOY_RUN_DIR/workflow-final.json"
echo ""

echo "All workflows deployed successfully."
