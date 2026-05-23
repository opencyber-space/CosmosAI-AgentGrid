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


#register sub workflow first
envsubst < "./workflow_spec-nested.json" > "./workflow_spec-nested_evaluated.json"
curl -X POST -d @"./workflow_spec-nested_evaluated.json" ${API_BASE_URL}/api/workflows
rm -f "./workflow_spec-nested_evaluated.json"

envsubst < "./workflow_spec.json" > "./workflow_spec_evaluated.json"
curl -X POST -d @"./workflow_spec_evaluated.json" ${API_BASE_URL}/api/workflows
rm -f "./workflow_spec_evaluated.json"