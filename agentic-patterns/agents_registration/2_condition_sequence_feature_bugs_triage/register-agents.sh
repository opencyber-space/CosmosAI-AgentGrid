#!/bin/bash

CUR_DIR=$(dirname "$(realpath "$0")")

bash $CUR_DIR/2_normalizer_agent1/register_agent.sh

bash $CUR_DIR/2_bux_fixer_agent3/register_agent.sh

bash $CUR_DIR/2_feature_agent6/register_agent.sh

bash $CUR_DIR/2_final_aggregator_agent9/register_agent.sh