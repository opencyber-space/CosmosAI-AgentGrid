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


envsubst < "./agent_functions_code_creator.json" > "./agent_functions_code_creator_evaluated.json"
curl -X POST \
    -H "Content-Type: application/json" \
    -d @"./agent_functions_code_creator_evaluated.json" \
    ${API_BASE_URL}/api/subjects
rm -f "./agent_functions_code_creator_evaluated.json"

envsubst < "./agent_functions_reviewer.json" > "./agent_functions_reviewer_evaluated.json"
curl -X POST \
    -H "Content-Type: application/json" \
    -d @"./agent_functions_reviewer_evaluated.json" \
    ${API_BASE_URL}/api/subjects
rm -f "./agent_functions_reviewer_evaluated.json"