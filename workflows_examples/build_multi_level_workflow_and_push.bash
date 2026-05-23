
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

bash build_docker.bash agent-workflow-collateral-evaluator
docker push ${DOCKER_REGISTRY}/agent-workflow-collateral-evaluator:latest

bash build_docker.bash agent-workflow-financial-profile
docker push ${DOCKER_REGISTRY}/agent-workflow-financial-profile:latest

bash build_docker.bash agent-workflow-fraud-score
docker push ${DOCKER_REGISTRY}/agent-workflow-fraud-score:latest

bash build_docker.bash agent-workflow-identity-verification
docker push ${DOCKER_REGISTRY}/agent-workflow-identity-verification:latest

bash build_docker.bash agent-workflow-loan-decision
docker push ${DOCKER_REGISTRY}/agent-workflow-loan-decision:latest

bash build_docker.bash agent-workflow-loan-risk-router
docker push ${DOCKER_REGISTRY}/agent-workflow-loan-risk-router:latest

bash build_docker.bash agent-workflow-market-risk
docker push ${DOCKER_REGISTRY}/agent-workflow-market-risk:latest

bash build_docker.bash agent-workflow-transaction-history
docker push ${DOCKER_REGISTRY}/agent-workflow-transaction-history:latest