#!/bin/bash

# ==============================================================================
# Script: unregister.sh
# Purpose: Unregister agent specs in bids_processing with AIOS API.
# Usage:
#   ./unregister.sh [agent_name]
# Example:
#   ./unregister.sh manager1_security_audit
#   ./unregister.sh (unregisters ALL 16 agents)
# ==============================================================================

GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$GIT_ROOT" ]; then
    GIT_ROOT=$(pwd)
fi
if [ -f "$GIT_ROOT/.env" ]; then
    set -a; source "$GIT_ROOT/.env"; set +a
else
    echo "Error: .env file MUST be present at $GIT_ROOT"
    exit 1
fi

TARGET_AGENT="$1"

ALL_AGENTS=(
    "manager1_security_audit"
    "subagent1_security_audit_code_scanner"
    "subagent2_security_audit_dep_checker"
    "subagent3_security_audit_compliance_verifier"
    "manager5_security_audit"
    "subagent1_security_audit_solo"
    "manager2_frontend"
    "subagent1_frontend_ui_component_builder"
    "subagent2_frontend_state_api_integrator"
    "subagent3_frontend_responsive_style_designer"
    "manager3_image_editing"
    "subagent1_image_editing_enhancer_restorer"
    "subagent2_image_editing_object_segmenter"
    "subagent3_image_editing_metadata_watermarker"
    "manager4_content_creation"
    "subagent1_content_creation_copywriter"
    "subagent2_content_creation_seo_optimizer"
    "subagent3_content_creation_proofreader_editor"
)

unregister_one() {
    local name="$1"
    local spec_file="$GIT_ROOT/bids_example/bids_processing/spec/${name}.json"
    local subject_id=$(jq -r '.identity.subject_id' "$spec_file")
    echo "---> Unregistering Agent Spec: ${subject_id}"
    curl -s -X DELETE "${API_BASE_URL}/api/subjects/${subject_id}"
    echo ""
}

echo "=========================================================="
echo "Unregistering Agent Specs in bids_processing..."
echo "=========================================================="
if [ -n "$TARGET_AGENT" ]; then
    unregister_one "$TARGET_AGENT"
else
    for agent in "${ALL_AGENTS[@]}"; do
        unregister_one "$agent"
    done
fi
echo "Unregistration completed."
