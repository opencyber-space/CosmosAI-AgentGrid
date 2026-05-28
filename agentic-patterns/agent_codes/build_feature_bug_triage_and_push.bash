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

bash build_docker.bash codingtask-code-text-normalizer
docker push ${DOCKER_REGISTRY}/codingtask-code-text-normalizer:latest

bash build_docker.bash codingtask-bug-fixer
docker push ${DOCKER_REGISTRY}/codingtask-bug-fixer:latest

bash build_docker.bash codingtask-feature-improver-agent
docker push ${DOCKER_REGISTRY}/codingtask-feature-improver-agent:latest

bash build_docker.bash codingtask-final-aggregator-agent
docker push ${DOCKER_REGISTRY}/codingtask-final-aggregator-agent:latest
