#!/bin/bash
CUR_DIR=$(dirname "$(realpath "$0")")
echo "Removing Hierarchical Company Agents..."
echo "Removing ceo-agent..."
bash $CUR_DIR/ceo-agent/remove-agent.sh
echo "Removing chief-of-staff-agent..."
bash $CUR_DIR/chief-of-staff-agent/remove-agent.sh
echo "Removing marketing-team-lead..."
bash $CUR_DIR/marketing-team-lead/remove-agent.sh
echo "Removing marketing-content-agent..."
bash $CUR_DIR/marketing-content-agent/remove-agent.sh
echo "Removing marketing-planning-agent..."
bash $CUR_DIR/marketing-planning-agent/remove-agent.sh
echo "Removing marketing-strategy-agent..."
bash $CUR_DIR/marketing-strategy-agent/remove-agent.sh
echo "Removing marketing-visual-agent..."
bash $CUR_DIR/marketing-visual-agent/remove-agent.sh
echo "Removing financial-team-lead..."
bash $CUR_DIR/financial-team-lead/remove-agent.sh
echo "Removing financial-controller-agent..."
bash $CUR_DIR/financial-controller-agent/remove-agent.sh
echo "Removing financial-strategist-agent..."
bash $CUR_DIR/financial-strategist-agent/remove-agent.sh
echo "Removing financial-accountant-agent..."
bash $CUR_DIR/financial-accountant-agent/remove-agent.sh
echo "Removing arch-design-team-lead..."
bash $CUR_DIR/arch-design-team-lead/remove-agent.sh
echo "Removing arch-senior-agent..."
bash $CUR_DIR/arch-senior-agent/remove-agent.sh
echo "Removing arch-junior-agent..."
bash $CUR_DIR/arch-junior-agent/remove-agent.sh
echo "Removing developer-team-lead..."
bash $CUR_DIR/developer-team-lead/remove-agent.sh
echo "Removing dev-frontend-agent..."
bash $CUR_DIR/dev-frontend-agent/remove-agent.sh
echo "Removing dev-backend-agent..."
bash $CUR_DIR/dev-backend-agent/remove-agent.sh
echo "Removing testing-team-lead..."
bash $CUR_DIR/testing-team-lead/remove-agent.sh
echo "Removing testing-dev-agent..."
bash $CUR_DIR/testing-dev-agent/remove-agent.sh
echo "All Hierarchical Company agents removed."
