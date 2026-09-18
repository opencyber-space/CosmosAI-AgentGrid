#!/bin/bash

# ==============================================================================
# Script: register.sh
# Purpose: Register agent specs in bids_processing with AIOS API.
# Usage:
#   ./register.sh [agent_name]
# Example:
#   ./register.sh manager1_security_audit
#   ./register.sh (registers ALL 16 agents)
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

CUR_DIR=$(dirname "$(realpath "$0")")
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

register_one() {
    local name="$1"
    local spec_file="$CUR_DIR/${name}.json"
    if [ ! -f "$spec_file" ]; then
        echo "Error: Spec file not found: $spec_file"
        return 1
    fi
    echo "---> Registering Agent Spec: ${name}"
    local eval_file="$CUR_DIR/${name}_evaluated.json"
    envsubst < "$spec_file" > "$eval_file"
    curl -s -X POST \
        -H "Content-Type: application/json" \
        -d @"$eval_file" \
        "${API_BASE_URL}/api/subjects"
    rm -f "$eval_file"
    echo ""
}

echo "=========================================================="
echo "Registering Agent Specs in bids_processing..."
echo "=========================================================="
if [ -n "$TARGET_AGENT" ]; then
    register_one "$TARGET_AGENT"
else
    for agent in "${ALL_AGENTS[@]}"; do
        register_one "$agent"
    done
fi
echo "Registration completed."
