#!/usr/bin/env bash
set -euo pipefail

# entrypoint.sh - choose runtime behavior based on $AGENT
# If AGENT is not provided, default to 'default' and run agent.py
AGENT=${AGENT:-default}
export PYTHONPATH="/app:${PYTHONPATH:-}"

if [ -f /app/.env ]; then
  set -a
  source /app/.env
  set +a
fi

case "${AGENT}" in
  default)
    echo "Starting default agent (agent.py)"
    exec python3 agent.py
    ;;
  # For bids_processing workflow agents
  manager1-security-audit)
    echo "Starting manager1-security-audit agent (bids_processing/nodes/manager1_security_audit.py)"
    exec python3 bids_processing/nodes/manager1_security_audit.py
    ;;
  subagent1-security-audit-code-scanner)
    echo "Starting subagent1-security-audit-code-scanner agent (bids_processing/nodes/subagent1_security_audit_code_scanner.py)"
    exec python3 bids_processing/nodes/subagent1_security_audit_code_scanner.py
    ;;
  subagent2-security-audit-dep-checker)
    echo "Starting subagent2-security-audit-dep-checker agent (bids_processing/nodes/subagent2_security_audit_dep_checker.py)"
    exec python3 bids_processing/nodes/subagent2_security_audit_dep_checker.py
    ;;
  subagent3-security-audit-compliance-verifier)
    echo "Starting subagent3-security-audit-compliance-verifier agent (bids_processing/nodes/subagent3_security_audit_compliance_verifier.py)"
    exec python3 bids_processing/nodes/subagent3_security_audit_compliance_verifier.py
    ;;
  manager5-security-audit)
    echo "Starting manager5-security-audit agent (bids_processing/nodes/manager5_security_audit.py)"
    exec python3 bids_processing/nodes/manager5_security_audit.py
    ;;
  subagent1-security-audit-solo)
    echo "Starting subagent1-security-audit-solo agent (bids_processing/nodes/subagent1_security_audit_solo.py)"
    exec python3 bids_processing/nodes/subagent1_security_audit_solo.py
    ;;
  manager2-frontend)
    echo "Starting manager2-frontend agent (bids_processing/nodes/manager2_frontend.py)"
    exec python3 bids_processing/nodes/manager2_frontend.py
    ;;
  subagent1-frontend-ui-component-builder)
    echo "Starting subagent1-frontend-ui-component-builder agent (bids_processing/nodes/subagent1_frontend_ui_component_builder.py)"
    exec python3 bids_processing/nodes/subagent1_frontend_ui_component_builder.py
    ;;
  subagent2-frontend-state-api-integrator)
    echo "Starting subagent2-frontend-state-api-integrator agent (bids_processing/nodes/subagent2_frontend_state_api_integrator.py)"
    exec python3 bids_processing/nodes/subagent2_frontend_state_api_integrator.py
    ;;
  subagent3-frontend-responsive-style-designer)
    echo "Starting subagent3-frontend-responsive-style-designer agent (bids_processing/nodes/subagent3_frontend_responsive_style_designer.py)"
    exec python3 bids_processing/nodes/subagent3_frontend_responsive_style_designer.py
    ;;
  manager3-image-editing)
    echo "Starting manager3-image-editing agent (bids_processing/nodes/manager3_image_editing.py)"
    exec python3 bids_processing/nodes/manager3_image_editing.py
    ;;
  subagent1-image-editing-enhancer-restorer)
    echo "Starting subagent1-image-editing-enhancer-restorer agent (bids_processing/nodes/subagent1_image_editing_enhancer_restorer.py)"
    exec python3 bids_processing/nodes/subagent1_image_editing_enhancer_restorer.py
    ;;
  subagent2-image-editing-object-segmenter)
    echo "Starting subagent2-image-editing-object-segmenter agent (bids_processing/nodes/subagent2_image_editing_object_segmenter.py)"
    exec python3 bids_processing/nodes/subagent2_image_editing_object_segmenter.py
    ;;
  subagent3-image-editing-metadata-watermarker)
    echo "Starting subagent3-image-editing-metadata-watermarker agent (bids_processing/nodes/subagent3_image_editing_metadata_watermarker.py)"
    exec python3 bids_processing/nodes/subagent3_image_editing_metadata_watermarker.py
    ;;
  manager4-content-creation)
    echo "Starting manager4-content-creation agent (bids_processing/nodes/manager4_content_creation.py)"
    exec python3 bids_processing/nodes/manager4_content_creation.py
    ;;
  subagent1-content-creation-copywriter)
    echo "Starting subagent1-content-creation-copywriter agent (bids_processing/nodes/subagent1_content_creation_copywriter.py)"
    exec python3 bids_processing/nodes/subagent1_content_creation_copywriter.py
    ;;
  subagent2-content-creation-seo-optimizer)
    echo "Starting subagent2-content-creation-seo-optimizer agent (bids_processing/nodes/subagent2_content_creation_seo_optimizer.py)"
    exec python3 bids_processing/nodes/subagent2_content_creation_seo_optimizer.py
    ;;
  subagent3-content-creation-proofreader-editor)
    echo "Starting subagent3-content-creation-proofreader-editor agent (bids_processing/nodes/subagent3_content_creation_proofreader_editor.py)"
    exec python3 bids_processing/nodes/subagent3_content_creation_proofreader_editor.py
    ;;
  *)
    echo "Starting no agent for '${AGENT}' (unknown mapping)"
    #exec python3 agent.py --agent "${AGENT}"
    ;;
esac

