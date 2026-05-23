
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

bash build_docker.bash marketing-orchestrator
docker push ${DOCKER_REGISTRY}/marketing-orchestrator:latest

#bash build_docker.bash marketing-worker
#docker push ${DOCKER_REGISTRY}/marketing-worker:latest

bash build_docker.bash marketing-content-creator-agent
docker push ${DOCKER_REGISTRY}/marketing-content-creator-agent:latest

bash build_docker.bash marketing-image-generator-agent
docker push ${DOCKER_REGISTRY}/marketing-image-generator-agent:latest

bash build_docker.bash marketing-image-reviewer-agent
docker push ${DOCKER_REGISTRY}/marketing-image-reviewer-agent:latest

bash build_docker.bash marketing-social-media-compaigner
docker push ${DOCKER_REGISTRY}/marketing-social-media-compaigner:latest
