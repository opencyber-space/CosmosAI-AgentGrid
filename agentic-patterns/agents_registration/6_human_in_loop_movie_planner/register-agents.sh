#!/bin/bash

# Get the directory where this script is located
CUR_DIR=$(dirname "$(realpath "$0")")

echo "Registering Movie Planner Agents..."

bash $CUR_DIR/planner_agent/register_agent.sh
bash $CUR_DIR/calendar_agent/register_agent.sh
bash $CUR_DIR/preference_agent/register_agent.sh
bash $CUR_DIR/bookmyshow_agent/register_agent.sh

echo "All Movie Planner agents registered."
