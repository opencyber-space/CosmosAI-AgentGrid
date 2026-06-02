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


curl -X DELETE ${API_BASE_URL}/api/subjects/clause-extractor-agent-2

curl -X DELETE ${API_BASE_URL}/api/subjects/risk-identifier-agent-2

curl -X DELETE ${API_BASE_URL}/api/subjects/compliance-checker-agent-2

curl -X DELETE ${API_BASE_URL}/api/subjects/negotiation-adviser-agent-2

curl -X DELETE ${API_BASE_URL}/api/subjects/legal-memo-agent-2

curl -X DELETE ${API_BASE_URL}/api/subjects/simple-workflow-router-agent
