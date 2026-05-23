#!/bin/bash

CUR_DIR=$(dirname "$(realpath "$0")")

bash $CUR_DIR/4_router_agent/register_agent.sh

bash $CUR_DIR/4_account_agent/register_agent.sh

bash $CUR_DIR/4_billing_agent/register_agent.sh

bash $CUR_DIR/4_tech_agent/register_agent.sh

bash $CUR_DIR/4_security_agent/register_agent.sh

bash $CUR_DIR/4_compliance_agent/register_agent.sh

bash $CUR_DIR/4_cx_agent/register_agent.sh

bash $CUR_DIR/4_synthesizer_agent/register_agent.sh