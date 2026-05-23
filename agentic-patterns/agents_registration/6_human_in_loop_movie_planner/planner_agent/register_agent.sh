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
envsubst < "$CUR_DIR/agent2.json" > "$CUR_DIR/agent2_evaluated.json"
curl -X POST -H "Content-Type: application/json" -d @"$CUR_DIR/agent2_evaluated.json" ${API_BASE_URL}/api/subjects
rm -f "$CUR_DIR/agent2_evaluated.json"
