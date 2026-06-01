#!/bin/bash
GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$GIT_ROOT" ]; then GIT_ROOT=$(pwd); fi
if [ -f "$GIT_ROOT/.env" ]; then set -a; source "$GIT_ROOT/.env"; set +a; else echo "Error: .env file MUST be present at $GIT_ROOT"; exit 1; fi

echo "Unregistering all workflows..."

curl -s -X DELETE "${API_BASE_URL}/api/workflows/workflow-software-company:1.0.0-production"
echo ""

curl -s -X DELETE "${API_BASE_URL}/api/workflows/workflow-cos:1.0.0-production"
echo ""

curl -s -X DELETE "${API_BASE_URL}/api/workflows/workflow-architecture-team:1.0.0-production"
echo ""

curl -s -X DELETE "${API_BASE_URL}/api/workflows/workflow-developer-team:1.0.0-production"
echo ""

curl -s -X DELETE "${API_BASE_URL}/api/workflows/workflow-financial-team:1.0.0-production"
echo ""

curl -s -X DELETE "${API_BASE_URL}/api/workflows/workflow-marketing-team:1.0.0-production"
echo ""

curl -s -X DELETE "${API_BASE_URL}/api/workflows/workflow-testing-team:1.0.0-production"
echo ""

echo "All workflows unregistered successfully."
