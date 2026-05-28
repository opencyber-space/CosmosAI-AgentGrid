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

bash build_docker.bash rfc-con-argument-generator
docker push ${DOCKER_REGISTRY}/rfc-con-argument-generator:latest

bash build_docker.bash rfc-consensus-synthesizer
docker push ${DOCKER_REGISTRY}/rfc-consensus-synthesizer:latest

bash build_docker.bash rfc-pro-argument-generator
docker push ${DOCKER_REGISTRY}/rfc-pro-argument-generator:latest

bash build_docker.bash rfc-summarizer
docker push ${DOCKER_REGISTRY}/rfc-summarizer:latest

bash build_docker.bash rfc-safeguards-proposer
docker push ${DOCKER_REGISTRY}/rfc-safeguards-proposer:latest
