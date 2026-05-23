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

# build_companyagents_and_push.bash

REGISTRY="${DOCKER_REGISTRY}"

AGENTS=(
  "company-ceo-agent"
  "company-chief-of-staff-agent"
  "company-marketing-team-lead"
  "company-marketing-content-agent"
  "company-marketing-planning-agent"
  "company-marketing-strategy-agent"
  "company-marketing-visual-agent"
  "company-financial-team-lead"
  "company-financial-controller-agent"
  "company-financial-strategist-agent"
  "company-financial-accountant-agent"
  "company-arch-design-team-lead"
  "company-arch-senior-agent"
  "company-arch-junior-agent"
  "company-developer-team-lead"
  "company-dev-frontend-agent"
  "company-dev-backend-agent"
  "company-testing-team-lead"
  "company-testing-dev-agent"
)

for AGENT in "${AGENTS[@]}"; do
  echo "--------------------------------------------------"
  echo "Building and Pushing: $AGENT"
  bash build_docker.bash "$AGENT"
  docker push "${REGISTRY}/${AGENT}:latest"
done

echo "--------------------------------------------------"
echo "All Hierarchical Company Agents Built and Pushed."
