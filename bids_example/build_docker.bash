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



#docker build --build-arg AGENT=brainstormer -f Dockerfile -t ${DOCKER_REGISTRY}/meeting-expert:latest .

set -euo pipefail

USAGE="Usage: $0 [AGENT]
Example: $0 meeting-expert-brainstormer   # builds image tagged meeting-expert-brainstormer:latest"

AGENT_DEFAULT="meeting-expert-brainstormer"
#check entrypoint.sh for valid agents

# Accept first positional argument as AGENT, otherwise use default
AGENT=${1:-$AGENT_DEFAULT}

if [[ -z "${AGENT// /}" ]]; then
	echo "ERROR: AGENT is empty"
	echo "$USAGE"
	exit 1
fi

# Normalize tag-friendly name (lowercase, remove spaces)
TAG_AGENT=$(echo "$AGENT" | tr '[:upper:]' '[:lower:]' | tr ' ' '-')

# Registry/repo prefix (adjust as needed)
REGISTRY="${DOCKER_REGISTRY}"
IMAGE_NAME="${TAG_AGENT}:latest"

echo "Building Docker image with AGENT=${AGENT} -> tag ${REGISTRY}/${IMAGE_NAME}"

cp "$GIT_ROOT/.env" .env || true

docker build --build-arg AGENT="${AGENT}" --build-arg DOCKER_REGISTRY="${DOCKER_REGISTRY}" -f Dockerfile -t "${REGISTRY}/${IMAGE_NAME}" .
# docker build --build-arg AGENT="${AGENT}" --build-arg DOCKER_REGISTRY="${DOCKER_REGISTRY}" -f Dockerfile_fast -t "${REGISTRY}/${IMAGE_NAME}" .

rm -f .env || true

echo "Built ${REGISTRY}/${IMAGE_NAME}"