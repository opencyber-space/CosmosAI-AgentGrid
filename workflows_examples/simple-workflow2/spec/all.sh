#!/bin/bash

# Get directory of current script
CUR_DIR=$(dirname "$(realpath "$0")")

echo "========================================="
echo "Beginning full lifecycle management for simple-workflow2 Agent..."
echo "========================================="

# 1. Removal of active agent deployments
if [ -f "$CUR_DIR/remove_agents.sh" ]; then
    echo "--> Running remove_agents.sh..."
    bash "$CUR_DIR/remove_agents.sh"
else
    echo "Error: remove_agents.sh not found at $CUR_DIR"
    exit 1
fi

sleepTime=40
echo "Waiting for $sleepTime seconds before unregistering..."
sleep $sleepTime

# 2. Unregistration of active agent subjects
if [ -f "$CUR_DIR/unregister_agents.sh" ]; then
    echo "--> Running unregister_agents.sh..."
    bash "$CUR_DIR/unregister_agents.sh"
else
    echo "Error: unregister_agents.sh not found at $CUR_DIR"
    exit 1
fi

# 3. Registration of active agent subjects
if [ -f "$CUR_DIR/register_agents.sh" ]; then
    echo "--> Running register_agents.sh..."
    bash "$CUR_DIR/register_agents.sh"
else
    echo "Error: register_agents.sh not found at $CUR_DIR"
    exit 1
fi

# 4. Deployment of active agent deployments
if [ -f "$CUR_DIR/deploy_agents.sh" ]; then
    echo "--> Running deploy_agents.sh..."
    bash "$CUR_DIR/deploy_agents.sh"
else
    echo "Error: deploy_agents.sh not found at $CUR_DIR"
    exit 1
fi

echo "========================================="
echo "Full lifecycle management for simple-workflow2 Agent completed successfully!"
echo "========================================="
