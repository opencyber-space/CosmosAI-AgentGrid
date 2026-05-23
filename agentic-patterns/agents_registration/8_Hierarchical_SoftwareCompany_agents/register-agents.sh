#!/bin/bash
CUR_DIR=$(dirname "$(realpath "$0")")
echo "Registering Hierarchical Company Agents..."
echo "Registering ceo-agent..."
bash $CUR_DIR/ceo-agent/register_agent.sh
echo "Registering chief-of-staff-agent..."
bash $CUR_DIR/chief-of-staff-agent/register_agent.sh
echo "Registering marketing-team-lead..."
bash $CUR_DIR/marketing-team-lead/register_agent.sh
echo "Registering marketing-content-agent..."
bash $CUR_DIR/marketing-content-agent/register_agent.sh
echo "Registering marketing-planning-agent..."
bash $CUR_DIR/marketing-planning-agent/register_agent.sh
echo "Registering marketing-strategy-agent..."
bash $CUR_DIR/marketing-strategy-agent/register_agent.sh
echo "Registering marketing-visual-agent..."
bash $CUR_DIR/marketing-visual-agent/register_agent.sh
echo "Registering financial-team-lead..."
bash $CUR_DIR/financial-team-lead/register_agent.sh
echo "Registering financial-controller-agent..."
bash $CUR_DIR/financial-controller-agent/register_agent.sh
echo "Registering financial-strategist-agent..."
bash $CUR_DIR/financial-strategist-agent/register_agent.sh
echo "Registering financial-accountant-agent..."
bash $CUR_DIR/financial-accountant-agent/register_agent.sh
echo "Registering arch-design-team-lead..."
bash $CUR_DIR/arch-design-team-lead/register_agent.sh
echo "Registering arch-senior-agent..."
bash $CUR_DIR/arch-senior-agent/register_agent.sh
echo "Registering arch-junior-agent..."
bash $CUR_DIR/arch-junior-agent/register_agent.sh
echo "Registering developer-team-lead..."
bash $CUR_DIR/developer-team-lead/register_agent.sh
echo "Registering dev-frontend-agent..."
bash $CUR_DIR/dev-frontend-agent/register_agent.sh
echo "Registering dev-backend-agent..."
bash $CUR_DIR/dev-backend-agent/register_agent.sh
echo "Registering testing-team-lead..."
bash $CUR_DIR/testing-team-lead/register_agent.sh
echo "Registering testing-dev-agent..."
bash $CUR_DIR/testing-dev-agent/register_agent.sh
echo "All Hierarchical Company agents registered."
