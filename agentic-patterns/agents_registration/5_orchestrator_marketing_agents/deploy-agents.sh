#!/bin/bash

CUR_DIR=$(dirname "$(realpath "$0")")

bash $CUR_DIR/orchestrator_agent/deploy-agent.sh

bash $CUR_DIR/content_creator_agent/deploy-agent.sh

bash $CUR_DIR/image_generator_agent/deploy-agent.sh

bash $CUR_DIR/image_reviewer_agent/deploy-agent.sh

bash $CUR_DIR/social_media_compaigner/deploy-agent.sh