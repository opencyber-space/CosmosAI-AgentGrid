
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

bash build_docker.bash meeting-expert-brainstormer
docker push ${DOCKER_REGISTRY}/meeting-expert-brainstormer:latest

bash build_docker.bash meeting-agenda-architect
docker push ${DOCKER_REGISTRY}/meeting-agenda-architect:latest

bash build_docker.bash meeting-invitation-crafter
docker push ${DOCKER_REGISTRY}/meeting-invitation-crafter:latest
