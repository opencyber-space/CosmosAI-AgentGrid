#!/bin/bash

# Get directory of current script
CUR_DIR=$(dirname "$(realpath "$0")")

echo "=========================================================="
echo "Deploying ALL Hierarchical Workflows..."
echo "=========================================================="

# echo -e "\n---> Executing deploy_architectureteam_workflow_test.bash..."
# bash "$CUR_DIR/deploy_architectureteam_workflow_test.bash"

# echo -e "\n---> Executing deploy_developerteam_workflow_test.bash..."
# bash "$CUR_DIR/deploy_developerteam_workflow_test.bash"

# echo -e "\n---> Executing deploy_financeteam_workflow_test.bash..."
# bash "$CUR_DIR/deploy_financeteam_workflow_test.bash"

# echo -e "\n---> Executing deploy_marketingteam_workflow_test.bash..."
# bash "$CUR_DIR/deploy_marketingteam_workflow_test.bash"

# echo -e "\n---> Executing deploy_testingteam_workflow_test.bash..."
# bash "$CUR_DIR/deploy_testingteam_workflow_test.bash"

# echo -e "\n---> Executing deploy_cos.sh..."
# bash "$CUR_DIR/deploy_cos.sh"

echo -e "\n---> Executing deploy_final_workflow.bash..."
bash "$CUR_DIR/deploy_final_workflow.bash"

echo -e "\n=========================================================="
echo "All Hierarchical Workflows deployed successfully."
echo "=========================================================="
