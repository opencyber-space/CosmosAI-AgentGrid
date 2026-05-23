#!/bin/bash

CUR_DIR=$(dirname "$(realpath "$0")")

bash $CUR_DIR/1_meeting-expert-brainstormer/register_agent.sh

bash $CUR_DIR/1_meeting-agenda-architect/register_agent.sh

bash $CUR_DIR/1_meeting-invitation-crafter/register_agent.sh