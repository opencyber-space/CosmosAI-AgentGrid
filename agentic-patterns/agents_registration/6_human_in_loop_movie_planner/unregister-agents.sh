#!/bin/bash

# Get the directory where this script is located
CUR_DIR=$(dirname "$(realpath "$0")")

echo "Unregistering Movie Planner Agents..."

bash $CUR_DIR/planner_agent/unregister_agent.sh
bash $CUR_DIR/calendar_agent/unregister_agent.sh
bash $CUR_DIR/preference_agent/unregister_agent.sh
bash $CUR_DIR/bookmyshow_agent/unregister_agent.sh

echo "All Movie Planner agents unregistered."
