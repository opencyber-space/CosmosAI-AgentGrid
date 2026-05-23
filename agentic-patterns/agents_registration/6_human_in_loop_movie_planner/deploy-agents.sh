#!/bin/bash

CUR_DIR=$(dirname "$(realpath "$0")")

bash $CUR_DIR/planner_agent/deploy-agent.sh

bash $CUR_DIR/calendar_agent/deploy-agent.sh

bash $CUR_DIR/preference_agent/deploy-agent.sh

bash $CUR_DIR/bookmyshow_agent/deploy-agent.sh