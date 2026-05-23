#!/bin/bash
CUR_DIR=$(dirname "$(realpath "$0")")
echo "Deploying Hierarchical Company Agents..."
echo "Deploying ceo-agent..."
bash $CUR_DIR/ceo-agent/deploy-agent.sh
echo "Deploying chief-of-staff-agent..."
bash $CUR_DIR/chief-of-staff-agent/deploy-agent.sh
echo "Deploying marketing-team-lead..."
bash $CUR_DIR/marketing-team-lead/deploy-agent.sh
echo "Deploying marketing-content-agent..."
bash $CUR_DIR/marketing-content-agent/deploy-agent.sh
echo "Deploying marketing-planning-agent..."
bash $CUR_DIR/marketing-planning-agent/deploy-agent.sh
echo "Deploying marketing-strategy-agent..."
bash $CUR_DIR/marketing-strategy-agent/deploy-agent.sh
echo "Deploying marketing-visual-agent..."
bash $CUR_DIR/marketing-visual-agent/deploy-agent.sh
echo "Deploying financial-team-lead..."
bash $CUR_DIR/financial-team-lead/deploy-agent.sh
echo "Deploying financial-controller-agent..."
bash $CUR_DIR/financial-controller-agent/deploy-agent.sh
echo "Deploying financial-strategist-agent..."
bash $CUR_DIR/financial-strategist-agent/deploy-agent.sh
echo "Deploying financial-accountant-agent..."
bash $CUR_DIR/financial-accountant-agent/deploy-agent.sh
echo "Deploying arch-design-team-lead..."
bash $CUR_DIR/arch-design-team-lead/deploy-agent.sh
echo "Deploying arch-senior-agent..."
bash $CUR_DIR/arch-senior-agent/deploy-agent.sh
echo "Deploying arch-junior-agent..."
bash $CUR_DIR/arch-junior-agent/deploy-agent.sh
echo "Deploying developer-team-lead..."
bash $CUR_DIR/developer-team-lead/deploy-agent.sh
echo "Deploying dev-frontend-agent..."
bash $CUR_DIR/dev-frontend-agent/deploy-agent.sh
echo "Deploying dev-backend-agent..."
bash $CUR_DIR/dev-backend-agent/deploy-agent.sh
echo "Deploying testing-team-lead..."
bash $CUR_DIR/testing-team-lead/deploy-agent.sh
echo "Deploying testing-dev-agent..."
bash $CUR_DIR/testing-dev-agent/deploy-agent.sh
echo "All Hierarchical Company agents deployed."
