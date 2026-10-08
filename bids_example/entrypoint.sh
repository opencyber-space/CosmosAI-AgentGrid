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
  # For video_analytics_bidding agents (6 roles x 5 companies).
  # AGENT is the subject_id, e.g. camfacesolution-bid-manager.

  # --- CamFaceSolution ---
  camfacesolution-bid-manager)
    echo "Starting camfacesolution-bid-manager agent (video_analytics_bidding/nodes/CamFaceSolution/bid_manager.py)"
    exec python3 video_analytics_bidding/nodes/CamFaceSolution/bid_manager.py
    ;;
  camfacesolution-ai-compliance)
    echo "Starting camfacesolution-ai-compliance agent (video_analytics_bidding/nodes/CamFaceSolution/ai_compliance.py)"
    exec python3 video_analytics_bidding/nodes/CamFaceSolution/ai_compliance.py
    ;;
  camfacesolution-sizing)
    echo "Starting camfacesolution-sizing agent (video_analytics_bidding/nodes/CamFaceSolution/sizing.py)"
    exec python3 video_analytics_bidding/nodes/CamFaceSolution/sizing.py
    ;;
  camfacesolution-finance)
    echo "Starting camfacesolution-finance agent (video_analytics_bidding/nodes/CamFaceSolution/finance.py)"
    exec python3 video_analytics_bidding/nodes/CamFaceSolution/finance.py
    ;;
  camfacesolution-bid-reviewer)
    echo "Starting camfacesolution-bid-reviewer agent (video_analytics_bidding/nodes/CamFaceSolution/bid_reviewer.py)"
    exec python3 video_analytics_bidding/nodes/CamFaceSolution/bid_reviewer.py
    ;;
  camfacesolution-head)
    echo "Starting camfacesolution-head agent (video_analytics_bidding/nodes/CamFaceSolution/head.py)"
    exec python3 video_analytics_bidding/nodes/CamFaceSolution/head.py
    ;;

  # --- MultiFaceTech ---
  multifacetech-bid-manager)
    echo "Starting multifacetech-bid-manager agent (video_analytics_bidding/nodes/MultiFaceTech/bid_manager.py)"
    exec python3 video_analytics_bidding/nodes/MultiFaceTech/bid_manager.py
    ;;
  multifacetech-ai-compliance)
    echo "Starting multifacetech-ai-compliance agent (video_analytics_bidding/nodes/MultiFaceTech/ai_compliance.py)"
    exec python3 video_analytics_bidding/nodes/MultiFaceTech/ai_compliance.py
    ;;
  multifacetech-sizing)
    echo "Starting multifacetech-sizing agent (video_analytics_bidding/nodes/MultiFaceTech/sizing.py)"
    exec python3 video_analytics_bidding/nodes/MultiFaceTech/sizing.py
    ;;
  multifacetech-finance)
    echo "Starting multifacetech-finance agent (video_analytics_bidding/nodes/MultiFaceTech/finance.py)"
    exec python3 video_analytics_bidding/nodes/MultiFaceTech/finance.py
    ;;
  multifacetech-bid-reviewer)
    echo "Starting multifacetech-bid-reviewer agent (video_analytics_bidding/nodes/MultiFaceTech/bid_reviewer.py)"
    exec python3 video_analytics_bidding/nodes/MultiFaceTech/bid_reviewer.py
    ;;
  multifacetech-head)
    echo "Starting multifacetech-head agent (video_analytics_bidding/nodes/MultiFaceTech/head.py)"
    exec python3 video_analytics_bidding/nodes/MultiFaceTech/head.py
    ;;

  # --- NewGenTech ---
  newgentech-bid-manager)
    echo "Starting newgentech-bid-manager agent (video_analytics_bidding/nodes/NewGenTech/bid_manager.py)"
    exec python3 video_analytics_bidding/nodes/NewGenTech/bid_manager.py
    ;;
  newgentech-ai-compliance)
    echo "Starting newgentech-ai-compliance agent (video_analytics_bidding/nodes/NewGenTech/ai_compliance.py)"
    exec python3 video_analytics_bidding/nodes/NewGenTech/ai_compliance.py
    ;;
  newgentech-sizing)
    echo "Starting newgentech-sizing agent (video_analytics_bidding/nodes/NewGenTech/sizing.py)"
    exec python3 video_analytics_bidding/nodes/NewGenTech/sizing.py
    ;;
  newgentech-finance)
    echo "Starting newgentech-finance agent (video_analytics_bidding/nodes/NewGenTech/finance.py)"
    exec python3 video_analytics_bidding/nodes/NewGenTech/finance.py
    ;;
  newgentech-bid-reviewer)
    echo "Starting newgentech-bid-reviewer agent (video_analytics_bidding/nodes/NewGenTech/bid_reviewer.py)"
    exec python3 video_analytics_bidding/nodes/NewGenTech/bid_reviewer.py
    ;;
  newgentech-head)
    echo "Starting newgentech-head agent (video_analytics_bidding/nodes/NewGenTech/head.py)"
    exec python3 video_analytics_bidding/nodes/NewGenTech/head.py
    ;;

  # --- UltraVideoTech ---
  ultravideotech-bid-manager)
    echo "Starting ultravideotech-bid-manager agent (video_analytics_bidding/nodes/UltraVideoTech/bid_manager.py)"
    exec python3 video_analytics_bidding/nodes/UltraVideoTech/bid_manager.py
    ;;
  ultravideotech-ai-compliance)
    echo "Starting ultravideotech-ai-compliance agent (video_analytics_bidding/nodes/UltraVideoTech/ai_compliance.py)"
    exec python3 video_analytics_bidding/nodes/UltraVideoTech/ai_compliance.py
    ;;
  ultravideotech-sizing)
    echo "Starting ultravideotech-sizing agent (video_analytics_bidding/nodes/UltraVideoTech/sizing.py)"
    exec python3 video_analytics_bidding/nodes/UltraVideoTech/sizing.py
    ;;
  ultravideotech-finance)
    echo "Starting ultravideotech-finance agent (video_analytics_bidding/nodes/UltraVideoTech/finance.py)"
    exec python3 video_analytics_bidding/nodes/UltraVideoTech/finance.py
    ;;
  ultravideotech-bid-reviewer)
    echo "Starting ultravideotech-bid-reviewer agent (video_analytics_bidding/nodes/UltraVideoTech/bid_reviewer.py)"
    exec python3 video_analytics_bidding/nodes/UltraVideoTech/bid_reviewer.py
    ;;
  ultravideotech-head)
    echo "Starting ultravideotech-head agent (video_analytics_bidding/nodes/UltraVideoTech/head.py)"
    exec python3 video_analytics_bidding/nodes/UltraVideoTech/head.py
    ;;

  # --- VideoProcTech ---
  videoproctech-bid-manager)
    echo "Starting videoproctech-bid-manager agent (video_analytics_bidding/nodes/VideoProcTech/bid_manager.py)"
    exec python3 video_analytics_bidding/nodes/VideoProcTech/bid_manager.py
    ;;
  videoproctech-ai-compliance)
    echo "Starting videoproctech-ai-compliance agent (video_analytics_bidding/nodes/VideoProcTech/ai_compliance.py)"
    exec python3 video_analytics_bidding/nodes/VideoProcTech/ai_compliance.py
    ;;
  videoproctech-sizing)
    echo "Starting videoproctech-sizing agent (video_analytics_bidding/nodes/VideoProcTech/sizing.py)"
    exec python3 video_analytics_bidding/nodes/VideoProcTech/sizing.py
    ;;
  videoproctech-finance)
    echo "Starting videoproctech-finance agent (video_analytics_bidding/nodes/VideoProcTech/finance.py)"
    exec python3 video_analytics_bidding/nodes/VideoProcTech/finance.py
    ;;
  videoproctech-bid-reviewer)
    echo "Starting videoproctech-bid-reviewer agent (video_analytics_bidding/nodes/VideoProcTech/bid_reviewer.py)"
    exec python3 video_analytics_bidding/nodes/VideoProcTech/bid_reviewer.py
    ;;
  videoproctech-head)
    echo "Starting videoproctech-head agent (video_analytics_bidding/nodes/VideoProcTech/head.py)"
    exec python3 video_analytics_bidding/nodes/VideoProcTech/head.py
    ;;
  *)
    echo "Starting no agent for '${AGENT}' (unknown mapping)"
    #exec python3 agent.py --agent "${AGENT}"
    ;;
esac

