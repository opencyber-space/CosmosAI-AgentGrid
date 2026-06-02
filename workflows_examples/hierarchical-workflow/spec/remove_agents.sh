#!/bin/bash

# Get directory of current script
CUR_DIR=$(dirname "$(realpath "$0")")

echo "=========================================================="
echo "Removing ALL Hierarchical Workflow Agent deployments..."
echo "=========================================================="

echo -e "\n---> Executing remove_architecture_agents.sh..."
bash "$CUR_DIR/remove_architecture_agents.sh"

echo -e "\n---> Executing remove_developer_agents.sh..."
bash "$CUR_DIR/remove_developer_agents.sh"

echo -e "\n---> Executing remove_finanace_agents.sh..."
bash "$CUR_DIR/remove_finanace_agents.sh"

echo -e "\n---> Executing remove_marketing_agents.sh..."
bash "$CUR_DIR/remove_marketing_agents.sh"

echo -e "\n---> Executing remove_testing_agents.sh..."
bash "$CUR_DIR/remove_testing_agents.sh"

echo -e "\n---> Executing remove_cos_agents.sh..."
bash "$CUR_DIR/remove_cos_agents.sh"

echo -e "\n---> Executing remove_ceo_agents.sh..."
bash "$CUR_DIR/remove_ceo_agents.sh"

echo -e "\n=========================================================="
echo "All Hierarchical Workflow Agent deployments removed."
echo "=========================================================="
