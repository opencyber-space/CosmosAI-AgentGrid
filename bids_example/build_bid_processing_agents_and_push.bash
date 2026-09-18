#!/bin/bash
set -euo pipefail

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

# Read optional parameter (defaults to all)
TARGET_FILTER="${1:-all}"

case "$TARGET_FILTER" in
  security|audit|sec)
    BID_PROCESSING_AGENTS=(
      "manager1-security-audit"
      "subagent1-security-audit-code-scanner"
      "subagent2-security-audit-dep-checker"
      "subagent3-security-audit-compliance-verifier"
      "manager5-security-audit"
      "subagent1-security-audit-solo"
    )
    ;;
  frontend|ui)
    BID_PROCESSING_AGENTS=(
      "manager2-frontend"
      "subagent1-frontend-ui-component-builder"
      "subagent2-frontend-state-api-integrator"
      "subagent3-frontend-responsive-style-designer"
    )
    ;;
  image|image_editing|media)
    BID_PROCESSING_AGENTS=(
      "manager3-image-editing"
      "subagent1-image-editing-enhancer-restorer"
      "subagent2-image-editing-object-segmenter"
      "subagent3-image-editing-metadata-watermarker"
    )
    ;;
  content|content_creation|copywriting)
    BID_PROCESSING_AGENTS=(
      "manager4-content-creation"
      "subagent1-content-creation-copywriter"
      "subagent2-content-creation-seo-optimizer"
      "subagent3-content-creation-proofreader-editor"
    )
    ;;
  all)
    BID_PROCESSING_AGENTS=(
      "manager1-security-audit"
      "subagent1-security-audit-code-scanner"
      "subagent2-security-audit-dep-checker"
      "subagent3-security-audit-compliance-verifier"
      "manager5-security-audit"
      "subagent1-security-audit-solo"
      "manager2-frontend"
      "subagent1-frontend-ui-component-builder"
      "subagent2-frontend-state-api-integrator"
      "subagent3-frontend-responsive-style-designer"
      "manager3-image-editing"
      "subagent1-image-editing-enhancer-restorer"
      "subagent2-image-editing-object-segmenter"
      "subagent3-image-editing-metadata-watermarker"
      "manager4-content-creation"
      "subagent1-content-creation-copywriter"
      "subagent2-content-creation-seo-optimizer"
      "subagent3-content-creation-proofreader-editor"
    )
    ;;
  *)
    echo "Error: Unknown filter option '$TARGET_FILTER'."
    echo "Usage: $0 [security|frontend|image_editing|content_creation|all]"
    exit 1
    ;;
esac

echo "Starting Docker builds and pushes for ${#BID_PROCESSING_AGENTS[@]} agent(s) (Filter: ${TARGET_FILTER})..."

for agent in "${BID_PROCESSING_AGENTS[@]}"; do
    echo "========================================================================="
    echo "Building Agent: ${agent}"
    echo "========================================================================="
    bash build_docker.bash "${agent}"
    
    echo "-------------------------------------------------------------------------"
    echo "Pushing Agent: ${agent} to ${DOCKER_REGISTRY}"
    echo "-------------------------------------------------------------------------"
    docker push "${DOCKER_REGISTRY}/${agent}:latest"
    echo "Successfully built and pushed ${agent}"
    echo ""
done

echo "Selected Bid Processing Agent(s) have been built and pushed successfully!"
