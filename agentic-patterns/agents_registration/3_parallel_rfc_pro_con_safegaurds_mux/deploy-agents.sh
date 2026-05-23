#!/bin/bash

CUR_DIR=$(dirname "$(realpath "$0")")

bash $CUR_DIR/3_rfc_summarizer/deploy-agent.sh

bash $CUR_DIR/3_pro_argument_generator/deploy-agent.sh

bash $CUR_DIR/3_con_argument_generator/deploy-agent.sh

bash $CUR_DIR/3_safeguards_proposer/deploy-agent.sh

bash $CUR_DIR/3_consensus_synthesizer/deploy-agent.sh