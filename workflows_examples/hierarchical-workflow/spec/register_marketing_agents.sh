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

CUR_DIR=$(dirname "$(realpath "$0")")

echo "Registering all 5 Marketing Workflow Agents..."

MARKETING_SPECS=(
  "agent_workflow_marketing_team_lead.json"
  "agent_workflow_marketing_strategy.json"
  "agent_workflow_marketing_planning.json"
  "agent_workflow_marketing_content.json"
  "agent_workflow_marketing_visual.json"
)

for spec_name in "${MARKETING_SPECS[@]}"; do
    spec_file="$CUR_DIR/${spec_name}"
    echo "Registering: ${spec_name}"
    base_name=$(basename "$spec_file" .json)
    eval_file="$CUR_DIR/${base_name}_evaluated.json"
    
    envsubst < "$spec_file" > "$eval_file"
    curl -s -X POST \
        -H "Content-Type: application/json" \
        -d @"$eval_file" \
        ${API_BASE_URL}/api/subjects
    rm -f "$eval_file"
    echo ""
done

echo "Marketing Workflow Agents registered successfully."
