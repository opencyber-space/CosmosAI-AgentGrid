
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

bash build_docker.bash movieplanner-planner-agent
docker push ${DOCKER_REGISTRY}/movieplanner-planner-agent:latest

bash build_docker.bash movieplanner-calendar-agent
docker push ${DOCKER_REGISTRY}/movieplanner-calendar-agent:latest

bash build_docker.bash movieplanner-preferences-agent
docker push ${DOCKER_REGISTRY}/movieplanner-preferences-agent:latest

bash build_docker.bash movieplanner-bookmyshow-agent
docker push ${DOCKER_REGISTRY}/movieplanner-bookmyshow-agent:latest
