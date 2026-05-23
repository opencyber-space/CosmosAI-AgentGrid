#!/bin/bash

CUR_DIR=$(dirname "$(realpath "$0")")

bash $CUR_DIR/4_router_agent/unregister_agent.sh

bash $CUR_DIR/4_account_agent/unregister_agent.sh

bash $CUR_DIR/4_billing_agent/unregister_agent.sh

bash $CUR_DIR/4_tech_agent/unregister_agent.sh

bash $CUR_DIR/4_security_agent/unregister_agent.sh

bash $CUR_DIR/4_compliance_agent/unregister_agent.sh

bash $CUR_DIR/4_cx_agent/unregister_agent.sh

bash $CUR_DIR/4_synthesizer_agent/unregister_agent.sh