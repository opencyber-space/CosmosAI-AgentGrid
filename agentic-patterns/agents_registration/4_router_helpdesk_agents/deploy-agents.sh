#!/bin/bash

CUR_DIR=$(dirname "$(realpath "$0")")

bash $CUR_DIR/4_router_agent/deploy-agent.sh

bash $CUR_DIR/4_account_agent/deploy-agent.sh

bash $CUR_DIR/4_billing_agent/deploy-agent.sh

bash $CUR_DIR/4_tech_agent/deploy-agent.sh

bash $CUR_DIR/4_security_agent/deploy-agent.sh

bash $CUR_DIR/4_compliance_agent/deploy-agent.sh

bash $CUR_DIR/4_cx_agent/deploy-agent.sh

bash $CUR_DIR/4_synthesizer_agent/deploy-agent.sh