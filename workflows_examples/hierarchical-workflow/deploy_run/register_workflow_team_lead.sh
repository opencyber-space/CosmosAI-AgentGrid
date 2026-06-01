#!/bin/bash
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

SPEC_FILE="$GIT_ROOT/workflows_examples/hierarchical-workflow/spec/agent_workflow_marketing_team_lead.json"
eval_file="$GIT_ROOT/workflows_examples/hierarchical-workflow/spec/agent_workflow_marketing_team_lead_evaluated.json"

echo "Registering Marketing Team Lead..."
envsubst < "$SPEC_FILE" > "$eval_file"
curl -X POST \
    -H "Content-Type: application/json" \
    -d @"$eval_file" \
    ${API_BASE_URL}/api/subjects
rm -f "$eval_file"

echo "Marketing Team Lead agents registered successfully."
