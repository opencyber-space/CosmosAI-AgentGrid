#!/bin/bash

# Get directory of current script
CUR_DIR=$(dirname "$(realpath "$0")")

echo "=========================================================="
echo "Deploying ALL Hierarchical Workflow Agents..."
echo "=========================================================="

echo -e "\n---> Executing deploy_architecture_agents.sh..."
bash "$CUR_DIR/deploy_architecture_agents.sh"

echo -e "\n---> Executing deploy_developer_agents.sh..."
bash "$CUR_DIR/deploy_developer_agents.sh"

echo -e "\n---> Executing deploy_finanace_agents.sh..."
bash "$CUR_DIR/deploy_finanace_agents.sh"

echo -e "\n---> Executing deploy_marketing_agents.sh..."
bash "$CUR_DIR/deploy_marketing_agents.sh"

echo -e "\n---> Executing deploy_testing_agents.sh..."
bash "$CUR_DIR/deploy_testing_agents.sh"

echo -e "\n---> Executing deploy_cos_agents.sh..."
bash "$CUR_DIR/deploy_cos_agents.sh"

echo -e "\n---> Executing deploy_ceo_agents.sh..."
bash "$CUR_DIR/deploy_ceo_agents.sh"

echo -e "\n=========================================================="
echo "All Hierarchical Workflow Agents deployed successfully."
echo "=========================================================="
