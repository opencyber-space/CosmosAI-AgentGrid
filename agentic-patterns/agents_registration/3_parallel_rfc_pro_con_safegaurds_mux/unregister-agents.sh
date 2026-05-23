#!/bin/bash

CUR_DIR=$(dirname "$(realpath "$0")")

bash $CUR_DIR/3_rfc_summarizer/unregister_agent.sh

bash $CUR_DIR/3_pro_argument_generator/unregister_agent.sh

bash $CUR_DIR/3_con_argument_generator/unregister_agent.sh

bash $CUR_DIR/3_safeguards_proposer/unregister_agent.sh

bash $CUR_DIR/3_consensus_synthesizer/unregister_agent.sh