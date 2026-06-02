#!/bin/bash

# Get directory of current script
CUR_DIR=$(dirname "$(realpath "$0")")

echo "=========================================================="
echo "Unregistering ALL Hierarchical Workflow Agents..."
echo "=========================================================="

echo -e "\n---> Executing unregister_architecture_agents.sh..."
bash "$CUR_DIR/unregister_architecture_agents.sh"

echo -e "\n---> Executing unregister_developer_agents.sh..."
bash "$CUR_DIR/unregister_developer_agents.sh"

echo -e "\n---> Executing unregister_finanace_agents.sh..."
bash "$CUR_DIR/unregister_finanace_agents.sh"

echo -e "\n---> Executing unregister_marketing_agents.sh..."
bash "$CUR_DIR/unregister_marketing_agents.sh"

echo -e "\n---> Executing unregister_testing_agents.sh..."
bash "$CUR_DIR/unregister_testing_agents.sh"

echo -e "\n---> Executing unregister_cos_agents.sh..."
bash "$CUR_DIR/unregister_cos_agents.sh"

echo -e "\n---> Executing unregister_ceo_agents.sh..."
bash "$CUR_DIR/unregister_ceo_agents.sh"

echo -e "\n=========================================================="
echo "All Hierarchical Workflow Agents unregistered successfully."
echo "=========================================================="
