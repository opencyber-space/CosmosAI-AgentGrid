#!/bin/bash

# Get directory of current script
CUR_DIR=$(dirname "$(realpath "$0")")

echo "========================================="
echo "Beginning full lifecycle management for Finance Agents..."
echo "========================================="

# 1. Removal of active agent deployments
if [ -f "$CUR_DIR/remove_finanace_agents.sh" ]; then
    echo "--> Running remove_finanace_agents.sh..."
    bash "$CUR_DIR/remove_finanace_agents.sh"
else
    echo "Error: remove_finanace_agents.sh not found at $CUR_DIR"
    exit 1
fi

sleepTime=40
echo "Waiting for $sleepTime seconds before unregistering..."
sleep $sleepTime

# 2. Unregistration of active agent subjects
if [ -f "$CUR_DIR/unregister_finanace_agents.sh" ]; then
    echo "--> Running unregister_finanace_agents.sh..."
    bash "$CUR_DIR/unregister_finanace_agents.sh"
else
    echo "Error: unregister_finanace_agents.sh not found at $CUR_DIR"
    exit 1
fi

# 3. Registration of active agent subjects
if [ -f "$CUR_DIR/register_finanace_agents.sh" ]; then
    echo "--> Running register_finanace_agents.sh..."
    bash "$CUR_DIR/register_finanace_agents.sh"
else
    echo "Error: register_finanace_agents.sh not found at $CUR_DIR"
    exit 1
fi

# 4. Deployment of active agent deployments
if [ -f "$CUR_DIR/deploy_finanace_agents.sh" ]; then
    echo "--> Running deploy_finanace_agents.sh..."
    bash "$CUR_DIR/deploy_finanace_agents.sh"
else
    echo "Error: deploy_finanace_agents.sh not found at $CUR_DIR"
    exit 1
fi

echo "========================================="
echo "Full lifecycle management for Finance Agents completed successfully!"
echo "========================================="
