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
  *)
    echo "Starting no agent for '${AGENT}' (unknown mapping)"
    #exec python3 agent.py --agent "${AGENT}"
    ;;
esac
