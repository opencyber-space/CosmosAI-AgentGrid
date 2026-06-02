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

bash build_docker.bash clause-extractor-agent-2
docker push ${DOCKER_REGISTRY}/clause-extractor-agent-2:latest

bash build_docker.bash compliance-checker-agent-2
docker push ${DOCKER_REGISTRY}/compliance-checker-agent-2:latest

bash build_docker.bash legal-memo-agent-2
docker push ${DOCKER_REGISTRY}/legal-memo-agent-2:latest

bash build_docker.bash negotiation-adviser-agent-2
docker push ${DOCKER_REGISTRY}/negotiation-adviser-agent-2:latest

bash build_docker.bash risk-identifier-agent-2
docker push ${DOCKER_REGISTRY}/risk-identifier-agent-2:latest

bash build_docker.bash simple-workflow-router-agent
docker push ${DOCKER_REGISTRY}/simple-workflow-router-agent:latest
