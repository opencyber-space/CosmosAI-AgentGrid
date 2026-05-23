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


# Build and push debateragents-seniorarchitectagent
bash build_docker.bash debateragents-seniorarchitectagent
docker push ${DOCKER_REGISTRY}/debateragents-seniorarchitectagent:latest

# Build and push debateragents-softwareagent
bash build_docker.bash debateragents-softwareagent
docker push ${DOCKER_REGISTRY}/debateragents-softwareagent:latest
