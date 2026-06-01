#!/usr/bin/env bash
set -euo pipefail

# entrypoint.sh - choose runtime behavior based on $AGENT
# If AGENT is not provided, default to 'default' and run agent.py
AGENT=${AGENT:-default}

case "${AGENT}" in
  default)
    echo "Starting default agent (agent.py)"
    exec python3 agent.py
    ;;
  #for single workflow agents
  clause-extractor-agent)
    echo "Starting clause-extractor-agent agent (simple-workflow/nodes/clause_extractor_agent.py)"
    # Example: pass the AGENT value as an argument to the python script
    exec python3 simple-workflow/nodes/clause_extractor_agent.py
    ;;
  compliance-checker-agent)
    echo "Starting compliance-checker-agent agent (simple-workflow/nodes/compliance_checker_agent.py)"
    exec python3 simple-workflow/nodes/compliance_checker_agent.py
    ;;
  legal-memo-agent)
    echo "Starting legal-memo-agent agent (simple-workflow/nodes/legal_memo_agent.py)"
    exec python3 simple-workflow/nodes/legal_memo_agent.py
    ;;
  negotiation-adviser-agent)
    echo "Starting negotiation-adviser-agent agent (simple-workflow/nodes/negotiation_adviser_agent.py)"
    exec python3 simple-workflow/nodes/negotiation_adviser_agent.py
    ;;
  risk-identifier-agent)
    echo "Starting risk-identifier-agent agent (simple-workflow/nodes/risk_identifier_agent.py)"
    exec python3 simple-workflow/nodes/risk_identifier_agent.py
    ;;

  #For Multi-level workflow agents
  agent-workflow-collateral-evaluator)
    echo "Starting agent-workflow-collateral-evaluator agent (multi-level-workflow/nodes/collateral_evaluator_agent.py)"
    exec python3 multi-level-workflow/nodes/collateral_evaluator_agent.py
    ;;
  agent-workflow-financial-profile)
    echo "Starting agent-workflow-financial-profile agent (multi-level-workflow/nodes/financial_profile_agent.py)"
    exec python3 multi-level-workflow/nodes/financial_profile_agent.py
    ;;
  agent-workflow-fraud-score)
    echo "Starting agent-workflow-fraud-score agent (multi-level-workflow/nodes/fraud_score_agent.py)"
    exec python3 multi-level-workflow/nodes/fraud_score_agent.py
    ;;
  agent-workflow-identity-verification)
    echo "Starting agent-workflow-identity-verification agent (multi-level-workflow/nodes/identity_verification_agent.py)"
    exec python3 multi-level-workflow/nodes/identity_verification_agent.py
    ;;
  agent-workflow-loan-decision)
    echo "Starting agent-workflow-loan-decision agent (multi-level-workflow/nodes/loan_decision_agent.py)"
    exec python3 multi-level-workflow/nodes/loan_decision_agent.py
    ;;
  agent-workflow-loan-risk-router)
    echo "Starting agent-workflow-loan-risk-router agent (multi-level-workflow/nodes/router_agent.py)"
    exec python3 multi-level-workflow/nodes/router_agent.py
    ;;
  agent-workflow-market-risk)
    echo "Starting agent-workflow-market-risk agent (multi-level-workflow/nodes/market_risk_agent.py)"
    exec python3 multi-level-workflow/nodes/market_risk_agent.py
    ;;
  agent-workflow-transaction-history)
    echo "Starting agent-workflow-transaction-history agent (multi-level-workflow/nodes/transaction_history_agent.py)"
    exec python3 multi-level-workflow/nodes/transaction_history_agent.py
    ;;
  
  # For Hierarchical workflow agents
  agent-workflow-ceo)
    echo "Starting agent-workflow-ceo agent (hierarchical-workflow/nodes/agent_ceo.py)"
    exec python3 hierarchical-workflow/nodes/agent_ceo.py
    ;;
  agent-workflow-cos)
    echo "Starting agent-workflow-cos agent (hierarchical-workflow/nodes/agent_cos.py)"
    exec python3 hierarchical-workflow/nodes/agent_cos.py
    ;;
  agent-workflow-financial-team-lead)
    echo "Starting agent-workflow-financial-team-lead agent (hierarchical-workflow/nodes/agent_financial_team_lead.py)"
    exec python3 hierarchical-workflow/nodes/agent_financial_team_lead.py
    ;;
  agent-workflow-financial-accountant)
    echo "Starting agent-workflow-financial-accountant agent (hierarchical-workflow/nodes/agent_financial_accountant.py)"
    exec python3 hierarchical-workflow/nodes/agent_financial_accountant.py
    ;;
  agent-workflow-financial-controller)
    echo "Starting agent-workflow-financial-controller agent (hierarchical-workflow/nodes/agent_financial_controller.py)"
    exec python3 hierarchical-workflow/nodes/agent_financial_controller.py
    ;;
  agent-workflow-financial-strategist)
    echo "Starting agent-workflow-financial-strategist agent (hierarchical-workflow/nodes/agent_financial_strategist.py)"
    exec python3 hierarchical-workflow/nodes/agent_financial_strategist.py
    ;;
  agent-workflow-marketing-team-lead)
    echo "Starting agent-workflow-marketing-team-lead agent (hierarchical-workflow/nodes/agent_marketing_team_lead.py)"
    exec python3 hierarchical-workflow/nodes/agent_marketing_team_lead.py
    ;;
  agent-workflow-marketing-content)
    echo "Starting agent-workflow-marketing-content agent (hierarchical-workflow/nodes/agent_marketing_content.py)"
    exec python3 hierarchical-workflow/nodes/agent_marketing_content.py
    ;;
  agent-workflow-marketing-planning)
    echo "Starting agent-workflow-marketing-planning agent (hierarchical-workflow/nodes/agent_marketing_planning.py)"
    exec python3 hierarchical-workflow/nodes/agent_marketing_planning.py
    ;;
  agent-workflow-marketing-strategy)
    echo "Starting agent-workflow-marketing-strategy agent (hierarchical-workflow/nodes/agent_marketing_strategy.py)"
    exec python3 hierarchical-workflow/nodes/agent_marketing_strategy.py
    ;;
  agent-workflow-marketing-visual)
    echo "Starting agent-workflow-marketing-visual agent (hierarchical-workflow/nodes/agent_marketing_visual.py)"
    exec python3 hierarchical-workflow/nodes/agent_marketing_visual.py
    ;;
  agent-workflow-testing-team-lead)
    echo "Starting agent-workflow-testing-team-lead agent (hierarchical-workflow/nodes/agent_testing_team_lead.py)"
    exec python3 hierarchical-workflow/nodes/agent_testing_team_lead.py
    ;;
  agent-workflow-testing-dev)
    echo "Starting agent-workflow-testing-dev agent (hierarchical-workflow/nodes/agent_testing_dev.py)"
    exec python3 hierarchical-workflow/nodes/agent_testing_dev.py
    ;;
  agent-workflow-developer-team-lead)
    echo "Starting agent-workflow-developer-team-lead agent (hierarchical-workflow/nodes/agent_developer_team_lead.py)"
    exec python3 hierarchical-workflow/nodes/agent_developer_team_lead.py
    ;;
  agent-workflow-dev-backend)
    echo "Starting agent-workflow-dev-backend agent (hierarchical-workflow/nodes/agent_dev_backend.py)"
    exec python3 hierarchical-workflow/nodes/agent_dev_backend.py
    ;;
  agent-workflow-dev-frontend)
    echo "Starting agent-workflow-dev-frontend agent (hierarchical-workflow/nodes/agent_dev_frontend.py)"
    exec python3 hierarchical-workflow/nodes/agent_dev_frontend.py
    ;;
  agent-workflow-arch-design-team-lead)
    echo "Starting agent-workflow-arch-design-team-lead agent (hierarchical-workflow/nodes/agent_arch_design_team_lead.py)"
    exec python3 hierarchical-workflow/nodes/agent_arch_design_team_lead.py
    ;;
  agent-workflow-arch-junior)
    echo "Starting agent-workflow-arch-junior agent (hierarchical-workflow/nodes/agent_arch_junior.py)"
    exec python3 hierarchical-workflow/nodes/agent_arch_junior.py
    ;;
  agent-workflow-arch-senior)
    echo "Starting agent-workflow-arch-senior agent (hierarchical-workflow/nodes/agent_arch_senior.py)"
    exec python3 hierarchical-workflow/nodes/agent_arch_senior.py
    ;;
  *)
    echo "Starting no agent for '${AGENT}' (unknown mapping)"
    #exec python3 agent.py --agent "${AGENT}"
    ;;
esac
