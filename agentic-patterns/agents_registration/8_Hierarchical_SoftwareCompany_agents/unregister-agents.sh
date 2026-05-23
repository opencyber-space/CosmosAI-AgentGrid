#!/bin/bash
CUR_DIR=$(dirname "$(realpath "$0")")
echo "Unregistering Hierarchical Company Agents..."
echo "Unregistering ceo-agent..."
bash $CUR_DIR/ceo-agent/unregister_agent.sh
echo "Unregistering chief-of-staff-agent..."
bash $CUR_DIR/chief-of-staff-agent/unregister_agent.sh
echo "Unregistering marketing-team-lead..."
bash $CUR_DIR/marketing-team-lead/unregister_agent.sh
echo "Unregistering marketing-content-agent..."
bash $CUR_DIR/marketing-content-agent/unregister_agent.sh
echo "Unregistering marketing-planning-agent..."
bash $CUR_DIR/marketing-planning-agent/unregister_agent.sh
echo "Unregistering marketing-strategy-agent..."
bash $CUR_DIR/marketing-strategy-agent/unregister_agent.sh
echo "Unregistering marketing-visual-agent..."
bash $CUR_DIR/marketing-visual-agent/unregister_agent.sh
echo "Unregistering financial-team-lead..."
bash $CUR_DIR/financial-team-lead/unregister_agent.sh
echo "Unregistering financial-controller-agent..."
bash $CUR_DIR/financial-controller-agent/unregister_agent.sh
echo "Unregistering financial-strategist-agent..."
bash $CUR_DIR/financial-strategist-agent/unregister_agent.sh
echo "Unregistering financial-accountant-agent..."
bash $CUR_DIR/financial-accountant-agent/unregister_agent.sh
echo "Unregistering arch-design-team-lead..."
bash $CUR_DIR/arch-design-team-lead/unregister_agent.sh
echo "Unregistering arch-senior-agent..."
bash $CUR_DIR/arch-senior-agent/unregister_agent.sh
echo "Unregistering arch-junior-agent..."
bash $CUR_DIR/arch-junior-agent/unregister_agent.sh
echo "Unregistering developer-team-lead..."
bash $CUR_DIR/developer-team-lead/unregister_agent.sh
echo "Unregistering dev-frontend-agent..."
bash $CUR_DIR/dev-frontend-agent/unregister_agent.sh
echo "Unregistering dev-backend-agent..."
bash $CUR_DIR/dev-backend-agent/unregister_agent.sh
echo "Unregistering testing-team-lead..."
bash $CUR_DIR/testing-team-lead/unregister_agent.sh
echo "Unregistering testing-dev-agent..."
bash $CUR_DIR/testing-dev-agent/unregister_agent.sh
echo "All Hierarchical Company agents unregistered."
