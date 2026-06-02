#!/bin/bash

# Get directory of current script
CUR_DIR=$(dirname "$(realpath "$0")")

echo "=========================================================="
echo "Beginning full lifecycle management for ALL Hierarchical Agents (PARALLEL MODE)..."
echo "=========================================================="

# Run all team scripts in the background
if [ -f "$CUR_DIR/all_architecture_agents.sh" ]; then
    echo "Starting Architecture Team Agents..."
    bash "$CUR_DIR/all_architecture_agents.sh" > /dev/null &
fi

if [ -f "$CUR_DIR/all_developer_agents.sh" ]; then
    echo "Starting Developer Team Agents..."
    bash "$CUR_DIR/all_developer_agents.sh" > /dev/null &
fi

if [ -f "$CUR_DIR/all_finanace_agents.sh" ]; then
    echo "Starting Finance Team Agents..."
    bash "$CUR_DIR/all_finanace_agents.sh" > /dev/null &
fi

if [ -f "$CUR_DIR/all_marketing_agents.sh" ]; then
    echo "Starting Marketing Team Agents..."
    bash "$CUR_DIR/all_marketing_agents.sh" > /dev/null &
fi

if [ -f "$CUR_DIR/all_testing_agents.sh" ]; then
    echo "Starting Testing Team Agents..."
    bash "$CUR_DIR/all_testing_agents.sh" > /dev/null &
fi

if [ -f "$CUR_DIR/all_cos_agents.sh" ]; then
    echo "Starting COS Team Agent..."
    bash "$CUR_DIR/all_cos_agents.sh" > /dev/null &
fi

# Run CEO Agent in the background as well
(
    echo "Starting CEO Agent..."
    if [ -f "$CUR_DIR/remove_ceo_agents.sh" ]; then bash "$CUR_DIR/remove_ceo_agents.sh" > /dev/null; fi
    sleep 40
    if [ -f "$CUR_DIR/unregister_ceo_agents.sh" ]; then bash "$CUR_DIR/unregister_ceo_agents.sh" > /dev/null; fi
    if [ -f "$CUR_DIR/register_ceo_agents.sh" ]; then bash "$CUR_DIR/register_ceo_agents.sh" > /dev/null; fi
    if [ -f "$CUR_DIR/deploy_ceo_agents.sh" ]; then bash "$CUR_DIR/deploy_ceo_agents.sh" > /dev/null; fi
) &

echo "=========================================================="
echo "All 7 agent groups are now running their lifecycle scripts in parallel."
echo "Waiting ~40 seconds for all tasks to complete..."
echo "=========================================================="

# Wait for all background processes to finish
wait

echo "=========================================================="
echo "Full lifecycle management for ALL Hierarchical Agents completed successfully!"
echo "=========================================================="
