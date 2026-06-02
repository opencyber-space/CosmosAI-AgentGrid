#!/bin/bash

# Get directory of current script
CUR_DIR=$(dirname "$(realpath "$0")")

echo "=========================================================="
echo "Beginning full lifecycle management for ALL Hierarchical Workflows..."
echo "=========================================================="

echo -e "\n---> [1/6] Deploying Architecture Team Workflow..."
if [ -f "$CUR_DIR/all_architectureteam.bash" ]; then
    bash "$CUR_DIR/all_architectureteam.bash" "no_deploy"
else
    echo "Warning: all_architectureteam.bash not found"
fi

echo -e "\n---> [2/6] Deploying Developer Team Workflow..."
if [ -f "$CUR_DIR/all_developerteam.bash" ]; then
    bash "$CUR_DIR/all_developerteam.bash" "no_deploy"
else
    echo "Warning: all_developerteam.bash not found"
fi

echo -e "\n---> [3/6] Deploying Finance Team Workflow..."
if [ -f "$CUR_DIR/all_financeteam.bash" ]; then
    bash "$CUR_DIR/all_financeteam.bash" "no_deploy"
else
    echo "Warning: all_financeteam.bash not found"
fi

echo -e "\n---> [4/6] Deploying Marketing Team Workflow..."
if [ -f "$CUR_DIR/all_marketingteam.bash" ]; then
    bash "$CUR_DIR/all_marketingteam.bash" "no_deploy"
else
    echo "Warning: all_marketingteam.bash not found"
fi

echo -e "\n---> [5/6] Deploying Testing Team Workflow..."
if [ -f "$CUR_DIR/all_testingteam.bash" ]; then
    bash "$CUR_DIR/all_testingteam.bash" "no_deploy"
else
    echo "Warning: all_testingteam.bash not found"
fi

echo -e "\n---> [6/6] Deploying Chief of Staff (COS) Team Workflow..."
if [ -f "$CUR_DIR/all_costeam.bash" ]; then
    bash "$CUR_DIR/all_costeam.bash" "no_deploy"
else
    echo "Warning: all_costeam.bash not found"
fi

echo -e "\n=========================================================="
echo "All sub-workflows deployed. Now deploying the Final CEO Workflow (workflow-software-company)..."
echo "=========================================================="

# 1. Removal of active workflow deployment
if [ -f "$CUR_DIR/remove_workflow_final.sh" ]; then
    echo "--> Running remove_workflow_final.sh..."
    bash "$CUR_DIR/remove_workflow_final.sh"
else
    echo "Error: remove_workflow_final.sh not found at $CUR_DIR"
    exit 1
fi

sleepTime=40
echo "Waiting for $sleepTime seconds before unregistering..."
sleep $sleepTime


# 2. Unregistration of the workflow spec
if [ -f "$CUR_DIR/unregister_workflow_final.sh" ]; then
    echo "--> Running unregister_workflow_final.sh..."
    bash "$CUR_DIR/unregister_workflow_final.sh"
else
    echo "Error: unregister_workflow_final.sh not found at $CUR_DIR"
    exit 1
fi

# 3. Registration of the workflow spec
if [ -f "$CUR_DIR/register_workflow_final.sh" ]; then
    echo "--> Running register_workflow_final.sh..."
    bash "$CUR_DIR/register_workflow_final.sh"
else
    echo "Error: register_workflow_final.sh not found at $CUR_DIR"
    exit 1
fi

# 4. Deployment of the workflow
if [ -f "$CUR_DIR/deploy_final_workflow.bash" ]; then
    echo "--> Running deploy_final_workflow.bash..."
    bash "$CUR_DIR/deploy_final_workflow.bash"
else
    echo "Error: deploy_final_workflow.bash not found at $CUR_DIR"
    exit 1
fi


echo "=========================================================="
echo "Full lifecycle management for the entire Hierarchical Agent Grid completed successfully!"
echo "=========================================================="
