#!/bin/bash

CUR_DIR=$(dirname "$(realpath "$0")")

bash $CUR_DIR/1_meeting-expert-brainstormer/unregister_agent.sh

bash $CUR_DIR/1_meeting-agenda-architect/unregister_agent.sh

bash $CUR_DIR/1_meeting-invitation-crafter/unregister_agent.sh