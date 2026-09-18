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


export SUBJECT_ID="meeting-topic-brainstormer"
export SUBJECT_DB_URL="${API_BASE_URL}"
export JOB_EXCHANGE_API_URL="${JOB_EXCHANGE_API_URL}"

python3 agent.py