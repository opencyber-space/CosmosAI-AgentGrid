#!/bin/bash

# Get directory of current script
CUR_DIR=$(dirname "$(realpath "$0")")

echo "========================================="
echo "Beginning full lifecycle management for Marketing Agents..."
echo "========================================="

# 1. Removal of active agent deployments
if [ -f "$CUR_DIR/remove_marketing_agents.sh" ]; then
    echo "--> Running remove_marketing_agents.sh..."
    bash "$CUR_DIR/remove_marketing_agents.sh"
else
    echo "Error: remove_marketing_agents.sh not found at $CUR_DIR"
    exit 1
fi

sleepTime=40
echo "Waiting for $sleepTime seconds before unregistering..."
sleep $sleepTime

# 2. Unregistration of active agent subjects
if [ -f "$CUR_DIR/unregister_marketing_agents.sh" ]; then
    echo "--> Running unregister_marketing_agents.sh..."
    bash "$CUR_DIR/unregister_marketing_agents.sh"
else
    echo "Error: unregister_marketing_agents.sh not found at $CUR_DIR"
    exit 1
fi

# 3. Registration of active agent subjects
if [ -f "$CUR_DIR/register_marketing_agents.sh" ]; then
    echo "--> Running register_marketing_agents.sh..."
    bash "$CUR_DIR/register_marketing_agents.sh"
else
    echo "Error: register_marketing_agents.sh not found at $CUR_DIR"
    exit 1
fi

# 4. Deployment of active agent deployments
if [ -f "$CUR_DIR/deploy_marketing_agents.sh" ]; then
    echo "--> Running deploy_marketing_agents.sh..."
    bash "$CUR_DIR/deploy_marketing_agents.sh"
else
    echo "Error: deploy_marketing_agents.sh not found at $CUR_DIR"
    exit 1
fi

echo "========================================="
echo "Full lifecycle management for Marketing Agents completed successfully!"
echo "========================================="
