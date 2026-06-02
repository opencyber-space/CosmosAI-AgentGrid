#!/bin/bash

# Get directory of current script
CUR_DIR=$(dirname "$(realpath "$0")")

echo "========================================="
echo "Beginning full lifecycle management for COS Team Workflow..."
echo "========================================="

if [ "$1" != "no_deploy" ]; then
    # 1. Removal of active workflow deployment
    if [ -f "$CUR_DIR/remove_workflow_costeam.sh" ]; then
        echo "--> Running remove_workflow_costeam.sh..."
        bash "$CUR_DIR/remove_workflow_costeam.sh"
    else
        echo "Error: remove_workflow_costeam.sh not found at $CUR_DIR"
        exit 1
    fi

    sleepTime=40
    echo "Waiting for $sleepTime seconds before unregistering..."
    sleep $sleepTime
else
    echo "Skipping removal and wait (no_deploy argument passed)"
fi

# 2. Unregistration of the workflow spec
if [ -f "$CUR_DIR/unregister_workflow_costeam.sh" ]; then
    echo "--> Running unregister_workflow_costeam.sh..."
    bash "$CUR_DIR/unregister_workflow_costeam.sh"
else
    echo "Error: unregister_workflow_costeam.sh not found at $CUR_DIR"
    exit 1
fi

# 3. Registration of the workflow spec
if [ -f "$CUR_DIR/register_workflow_cos.sh" ]; then
    echo "--> Running register_workflow_cos.sh..."
    bash "$CUR_DIR/register_workflow_cos.sh"
else
    echo "Error: register_workflow_cos.sh not found at $CUR_DIR"
    exit 1
fi

if [ "$1" != "no_deploy" ]; then
    # 4. Deployment of the workflow
    if [ -f "$CUR_DIR/deploy_cos.sh" ]; then
        echo "--> Running deploy_cos.sh..."
        bash "$CUR_DIR/deploy_cos.sh"
    else
        echo "Error: deploy_cos.sh not found at $CUR_DIR"
        exit 1
    fi
else
    echo "Skipping deployment (no_deploy argument passed)"
fi

echo "========================================="
echo "Full lifecycle management for COS Team Workflow completed successfully!"
echo "========================================="
