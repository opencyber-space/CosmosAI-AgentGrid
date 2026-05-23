
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

bash build_docker.bash router-agent
docker push ${DOCKER_REGISTRY}/router-agent:latest

bash build_docker.bash billing-agent
docker push ${DOCKER_REGISTRY}/billing-agent:latest

bash build_docker.bash tech-agent
docker push ${DOCKER_REGISTRY}/tech-agent:latest

bash build_docker.bash account-agent
docker push ${DOCKER_REGISTRY}/account-agent:latest

bash build_docker.bash security-agent
docker push ${DOCKER_REGISTRY}/security-agent:latest

bash build_docker.bash compliance-agent
docker push ${DOCKER_REGISTRY}/compliance-agent:latest

bash build_docker.bash cx-agent
docker push ${DOCKER_REGISTRY}/cx-agent:latest

bash build_docker.bash synthesizer-agent
docker push ${DOCKER_REGISTRY}/synthesizer-agent:latest