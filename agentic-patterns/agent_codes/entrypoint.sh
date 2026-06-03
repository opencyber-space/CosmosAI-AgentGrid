#!/usr/bin/env bash
set -euo pipefail

# entrypoint.sh - choose runtime behavior based on $AGENT
# If AGENT is not provided, default to 'default' and run agent.py
AGENT=${AGENT:-default}

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
  #for 1_Sequential_Pattern agents
  meeting-expert-brainstormer)
    echo "Starting meeting-expert-brainstormer agent (agent_meeting_expert_brainstormer.py)"
    exec python3 agent_meeting_expert_brainstormer.py
    ;;
  meeting-agenda-architect)
    echo "Starting meeting-agenda-architect agent (agent_meeting_agenda_architect.py)"
    exec python3 agent_meeting_agenda_architect.py
    ;;
  meeting-invitation-crafter)
    echo "Starting meeting-invitation-crafter agent (agent_meeting_invitation_crafter.py)"
    exec python3 agent_meeting_invitation_crafter.py
    ;;

  #for 2_condition_sequence_feature_bugs_triage agents
  codingtask-code-text-normalizer)
    echo "Starting codingtask-code-text-normalizer agent (agent_codingtask_code_text_normalizer.py)"
    exec python3 agent_codingtask_code_text_normalizer.py
    ;;
  codingtask-bug-fixer)
    echo "Starting codingtask-bug-fixer agent (agent_codingtask_bug_fixer.py)"
    exec python3 agent_codingtask_bug_fixer.py
    ;;
  codingtask-feature-improver-agent)
    echo "Starting codingtask-feature-improver agent (agent_codingtask_feature_improver.py)"
    exec python3 agent_codingtask_feature_improver.py
    ;;
  codingtask-final-aggregator-agent)
    echo "Starting codingtask-final-aggregator agent (agent_codingtask_final_aggregator.py)"
    exec python3 agent_codingtask_final_aggregator.py
    ;;

  #for 3_parallel_rfc_pro_con_safegaurds_mux agents
  rfc-con-argument-generator)
    echo "Starting con-argument-generator agent (agent_rfc_con_argument_generator.py)"
    exec python3 agent_rfc_consensus_synthesizer.py
    ;;
  rfc-consensus-synthesizer)
    echo "Starting consensus-synthesizer agent (agent_rfc_consensus_synthesizer.py)"
    exec python3 agent_rfc_consensus_synthesizer.py
    ;;
  rfc-pro-argument-generator)
    echo "Starting pro-argument-generator agent (agent_rfc_pro_argument_generator.py)"
    exec python3 agent_rfc_pro_argument_generator.py
    ;;
  rfc-summarizer)
    echo "Starting rfc-summarizer agent (agent_rfc_rfc_summarizer.py)"
    exec python3 agent_rfc_rfc_summarizer.py
    ;;
  rfc-safeguards-proposer)
    echo "Starting safeguards-proposer agent (agent_rfc_safeguards_proposer.py)"
    exec python3 agent_rfc_safeguards_proposer.py
    ;;

  #for 4_router_helpdesk_agents
  router-agent)
    echo "Starting router-agent agent (agent_helpdesk_router_agent.py)"
    exec python3 agent_helpdesk_router_agent.py
    ;;
  billing-agent)
    echo "Starting billing-agent agent (agent_helpdesk_billing_agent.py)"
    exec python3 agent_helpdesk_billing_agent.py
    ;;
  tech-agent)
    echo "Starting tech-agent agent (agent_helpdesk_tech_agent.py)"
    exec python3 agent_helpdesk_tech_agent.py
    ;;
  account-agent)
    echo "Starting account-agent agent (agent_helpdesk_account_agent.py)"
    exec python3 agent_helpdesk_account_agent.py
    ;;
  security-agent)
    echo "Starting security-agent agent (agent_helpdesk_security_agent.py)"
    exec python3 agent_helpdesk_security_agent.py
    ;;
  compliance-agent)
    echo "Starting compliance-agent agent (agent_helpdesk_compliance_agent.py)"
    exec python3 agent_helpdesk_compliance_agent.py
    ;;
  cx-agent)
    echo "Starting cx-agent agent (agent_helpdesk_cx_agent.py)"
    exec python3 agent_helpdesk_cx_agent.py
    ;;
  synthesizer-agent)
    echo "Starting synthesizer-agent agent (agent_helpdesk_synthesizer_agent.py)"
    exec python3 agent_helpdesk_synthesizer_agent.py
    ;;

  #for 5_orchestrator_marketing_agents
  marketing-orchestrator)
    echo "Starting marketing-orchestrator agent (agent_marketing_orchestrator.py)"
    exec python3 agent_marketing_orchestrator.py
    ;;
  marketing-content-creator-agent)
    echo "Starting marketing-content-creator-agent agent (agent_marketing_content_creator.py)"
    exec python3 agent_marketing_content_creator.py
    ;;
  marketing-image-generator-agent)
    echo "Starting marketing-image-generator-agent agent (agent_marketing_image_generator.py)"
    exec python3 agent_marketing_image_generator.py
    ;;
  marketing-image-reviewer-agent)
    echo "Starting marketing-image-reviewer-agent agent (agent_marketing_image_reviewer.py)"
    exec python3 agent_marketing_image_reviewer.py
    ;;
  marketing-social-media-compaigner)
    echo "Starting marketing-social-media-compaigner agent (agent_marketing_social_media_campaigner.py)"
    exec python3 agent_marketing_social_media_campaigner.py
    ;;

  #for 6_human_in_loop_movie_planner agents
  movieplanner-planner-agent)
    echo "Starting movieplanner-planner-agent agent (agent_movieplanner_planner_agent.py)"
    exec python3 agent_movieplanner_planner_agent.py
    ;;
  movieplanner-calendar-agent)
    echo "Starting movieplanner-calendar-agent agent (agent_movieplanner_calendar_agent.py)"
    exec python3 agent_movieplanner_calendar_agent.py
    ;;
  movieplanner-preferences-agent)
    echo "Starting movieplanner-preferences-agent agent (agent_movieplanner_preference_agent.py)"
    exec python3 agent_movieplanner_preference_agent.py
    ;;
  movieplanner-bookmyshow-agent)
    echo "Starting movieplanner-bookmyshow-agent agent (agent_movieplanner_bookmyshow_agent.py)"
    exec python3 agent_movieplanner_bookmyshow_agent.py
    ;;

  #for 7_CriticReflection_SoftwareArchitect_agents
  debateragents-seniorarchitectagent)
    echo "Starting debateragents-seniorarchitectagent agent (agent_debateragents_seniorarchitectagent.py)"
    exec python3 agent_debateragents_seniorarchitectagent.py
    ;;
  debateragents-softwareagent)
    echo "Starting debateragents-softwareagent agent (agent_debateragents_softwareagent.py)"
    exec python3 agent_debateragents_softwareagent.py
    ;;

  #for 8_Hierarchical_SoftwareCompany_agents
  company-ceo-agent)
    echo "Starting company-ceo-agent (hierarchical_agents_dsl/agent_ceo.py)"
    exec python3 hierarchical_agents_dsl/agent_ceo.py
    ;;
  company-chief-of-staff-agent)
    echo "Starting company-chief-of-staff-agent (hierarchical_agents_dsl/agent_cos.py)"
    exec python3 hierarchical_agents_dsl/agent_cos.py
    ;;
  company-marketing-team-lead)
    echo "Starting company-marketing-team-lead (hierarchical_agents_dsl/agent_marketing_team_lead.py)"
    exec python3 hierarchical_agents_dsl/agent_marketing_team_lead.py
    ;;
  company-marketing-content-agent)
    echo "Starting company-marketing-content-agent (hierarchical_agents_dsl/agent_marketing_content.py)"
    exec python3 hierarchical_agents_dsl/agent_marketing_content.py
    ;;
  company-marketing-planning-agent)
    echo "Starting company-marketing-planning-agent (hierarchical_agents_dsl/agent_marketing_planning.py)"
    exec python3 hierarchical_agents_dsl/agent_marketing_planning.py
    ;;
  company-marketing-strategy-agent)
    echo "Starting company-marketing-strategy-agent (hierarchical_agents_dsl/agent_marketing_strategy.py)"
    exec python3 hierarchical_agents_dsl/agent_marketing_strategy.py
    ;;
  company-marketing-visual-agent)
    echo "Starting company-marketing-visual-agent (hierarchical_agents_dsl/agent_marketing_visual.py)"
    exec python3 hierarchical_agents_dsl/agent_marketing_visual.py
    ;;
  company-financial-team-lead)
    echo "Starting company-financial-team-lead (hierarchical_agents_dsl/agent_financial_team_lead.py)"
    exec python3 hierarchical_agents_dsl/agent_financial_team_lead.py
    ;;
  company-financial-controller-agent)
    echo "Starting company-financial-controller-agent (hierarchical_agents_dsl/agent_financial_controller.py)"
    exec python3 hierarchical_agents_dsl/agent_financial_controller.py
    ;;
  company-financial-strategist-agent)
    echo "Starting company-financial-strategist-agent (hierarchical_agents_dsl/agent_financial_strategist.py)"
    exec python3 hierarchical_agents_dsl/agent_financial_strategist.py
    ;;
  company-financial-accountant-agent)
    echo "Starting company-financial-accountant-agent (hierarchical_agents_dsl/agent_financial_accountant.py)"
    exec python3 hierarchical_agents_dsl/agent_financial_accountant.py
    ;;
  company-arch-design-team-lead)
    echo "Starting company-arch-design-team-lead (hierarchical_agents_dsl/agent_arch_design_team_lead.py)"
    exec python3 hierarchical_agents_dsl/agent_arch_design_team_lead.py
    ;;
  company-arch-senior-agent)
    echo "Starting company-arch-senior-agent (hierarchical_agents_dsl/agent_arch_senior.py)"
    exec python3 hierarchical_agents_dsl/agent_arch_senior.py
    ;;
  company-arch-junior-agent)
    echo "Starting company-arch-junior-agent (hierarchical_agents_dsl/agent_arch_junior.py)"
    exec python3 hierarchical_agents_dsl/agent_arch_junior.py
    ;;
  company-developer-team-lead)
    echo "Starting company-developer-team-lead (hierarchical_agents_dsl/agent_developer_team_lead.py)"
    exec python3 hierarchical_agents_dsl/agent_developer_team_lead.py
    ;;
  company-dev-frontend-agent)
    echo "Starting company-dev-frontend-agent (hierarchical_agents_dsl/agent_dev_frontend.py)"
    exec python3 hierarchical_agents_dsl/agent_dev_frontend.py
    ;;
  company-dev-backend-agent)
    echo "Starting company-dev-backend-agent (hierarchical_agents_dsl/agent_dev_backend.py)"
    exec python3 hierarchical_agents_dsl/agent_dev_backend.py
    ;;
  company-testing-team-lead)
    echo "Starting company-testing-team-lead (hierarchical_agents_dsl/agent_testing_team_lead.py)"
    exec python3 hierarchical_agents_dsl/agent_testing_team_lead.py
    ;;
  company-testing-dev-agent)
    echo "Starting company-testing-dev-agent (hierarchical_agents_dsl/agent_testing_dev.py)"
    exec python3 hierarchical_agents_dsl/agent_testing_dev.py
    ;;
  *)
    echo "Starting no agent for '${AGENT}' (unknown mapping)"
    #exec python3 agent.py --agent "${AGENT}"
    ;;
esac
