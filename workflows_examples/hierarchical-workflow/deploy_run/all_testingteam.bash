#!/bin/bash

# Get directory of current script
CUR_DIR=$(dirname "$(realpath "$0")")

echo "========================================="
echo "Beginning full lifecycle management for Testing Team Workflow..."
echo "========================================="

# 1. Removal of active workflow deployment
if [ -f "$CUR_DIR/remove_workflow_testingteam.sh" ]; then
    echo "--> Running remove_workflow_testingteam.sh..."
    bash "$CUR_DIR/remove_workflow_testingteam.sh"
else
    echo "Error: remove_workflow_testingteam.sh not found at $CUR_DIR"
    exit 1
fi

sleepTime=40
echo "Waiting for $sleepTime seconds before unregistering..."
sleep $sleepTime

# 2. Unregistration of the workflow spec
if [ -f "$CUR_DIR/unregister_workflow_testingteam.sh" ]; then
    echo "--> Running unregister_workflow_testingteam.sh..."
    bash "$CUR_DIR/unregister_workflow_testingteam.sh"
else
    echo "Error: unregister_workflow_testingteam.sh not found at $CUR_DIR"
    exit 1
fi

# 3. Registration of the workflow spec
if [ -f "$CUR_DIR/register_workflow_testingteam.sh" ]; then
    echo "--> Running register_workflow_testingteam.sh..."
    bash "$CUR_DIR/register_workflow_testingteam.sh"
else
    echo "Error: register_workflow_testingteam.sh not found at $CUR_DIR"
    exit 1
fi

# 4. Deployment of the workflow
if [ -f "$CUR_DIR/deploy_testingteam_workflow_test.bash" ]; then
    echo "--> Running deploy_testingteam_workflow_test.bash..."
    bash "$CUR_DIR/deploy_testingteam_workflow_test.bash"
else
    echo "Error: deploy_testingteam_workflow_test.bash not found at $CUR_DIR"
    exit 1
fi

echo "========================================="
echo "Full lifecycle management for Testing Team Workflow completed successfully!"
echo "========================================="
