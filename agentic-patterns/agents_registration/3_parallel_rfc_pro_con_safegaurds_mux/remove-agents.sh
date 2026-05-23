
#!/bin/bash

CUR_DIR=$(dirname "$(realpath "$0")")

bash $CUR_DIR/3_rfc_summarizer/remove-agent.sh

bash $CUR_DIR/3_pro_argument_generator/remove-agent.sh

bash $CUR_DIR/3_con_argument_generator/remove-agent.sh

bash $CUR_DIR/3_safeguards_proposer/remove-agent.sh

bash $CUR_DIR/3_consensus_synthesizer/remove-agent.sh