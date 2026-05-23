#!/bin/bash

CUR_DIR=$(dirname "$(realpath "$0")")

bash $CUR_DIR/3_rfc_summarizer/register_agent.sh

bash $CUR_DIR/3_pro_argument_generator/register_agent.sh

bash $CUR_DIR/3_con_argument_generator/register_agent.sh

bash $CUR_DIR/3_safeguards_proposer/register_agent.sh

bash $CUR_DIR/3_consensus_synthesizer/register_agent.sh