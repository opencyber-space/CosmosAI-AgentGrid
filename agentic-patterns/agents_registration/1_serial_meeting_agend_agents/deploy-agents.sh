#!/bin/bash

CUR_DIR=$(dirname "$(realpath "$0")")

bash $CUR_DIR/1_meeting-expert-brainstormer/deploy-agent.sh

bash $CUR_DIR/1_meeting-agenda-architect/deploy-agent.sh

bash $CUR_DIR/1_meeting-invitation-crafter/deploy-agent.sh
