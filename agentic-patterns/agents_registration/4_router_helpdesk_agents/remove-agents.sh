
#!/bin/bash

CUR_DIR=$(dirname "$(realpath "$0")")

bash $CUR_DIR/4_router_agent/remove-agent.sh

bash $CUR_DIR/4_account_agent/remove-agent.sh

bash $CUR_DIR/4_billing_agent/remove-agent.sh

bash $CUR_DIR/4_tech_agent/remove-agent.sh

bash $CUR_DIR/4_security_agent/remove-agent.sh

bash $CUR_DIR/4_compliance_agent/remove-agent.sh

bash $CUR_DIR/4_cx_agent/remove-agent.sh

bash $CUR_DIR/4_synthesizer_agent/remove-agent.sh