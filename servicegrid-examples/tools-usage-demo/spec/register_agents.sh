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


envsubst < "./agent_tool_user_demo.json" > "./agent_tool_user_demo_evaluated.json"
curl -X POST \
    -H "Content-Type: application/json" \
    -d @"./agent_tool_user_demo_evaluated.json" \
    ${API_BASE_URL}/api/subjects
rm -f "./agent_tool_user_demo_evaluated.json"