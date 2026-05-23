#!/bin/bash

CUR_DIR=$(dirname "$(realpath "$0")")

bash $CUR_DIR/orchestrator_agent/register_agent.sh

bash $CUR_DIR/content_creator_agent/register_agent.sh

bash $CUR_DIR/image_generator_agent/register_agent.sh

bash $CUR_DIR/image_reviewer_agent/register_agent.sh

bash $CUR_DIR/social_media_compaigner/register_agent.sh