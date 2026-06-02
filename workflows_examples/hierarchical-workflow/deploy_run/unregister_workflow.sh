#!/bin/bash

# Get directory of current script
CUR_DIR=$(dirname "$(realpath "$0")")

echo "=========================================================="
echo "Unregistering ALL Hierarchical Workflows..."
echo "=========================================================="

echo -e "\n---> Executing unregister_workflow_architectureteam.sh..."
bash "$CUR_DIR/unregister_workflow_architectureteam.sh"

echo -e "\n---> Executing unregister_workflow_developerteam.sh..."
bash "$CUR_DIR/unregister_workflow_developerteam.sh"

echo -e "\n---> Executing unregister_workflow_financeteam.sh..."
bash "$CUR_DIR/unregister_workflow_financeteam.sh"

echo -e "\n---> Executing unregister_workflow_marketingteam.sh..."
bash "$CUR_DIR/unregister_workflow_marketingteam.sh"

echo -e "\n---> Executing unregister_workflow_testingteam.sh..."
bash "$CUR_DIR/unregister_workflow_testingteam.sh"

echo -e "\n---> Executing unregister_workflow_costeam.sh..."
bash "$CUR_DIR/unregister_workflow_costeam.sh"

echo -e "\n---> Executing unregister_workflow_final.sh..."
bash "$CUR_DIR/unregister_workflow_final.sh"

echo -e "\n=========================================================="
echo "All Hierarchical Workflows unregistered successfully."
echo "=========================================================="
