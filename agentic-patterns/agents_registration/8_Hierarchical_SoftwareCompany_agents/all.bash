#!/bin/bash
CUR_DIR=$(dirname "$(realpath "$0")")

echo "Starting All-in-One Hierarchical Company Setup..."

bash $CUR_DIR/remove-agents.sh
echo "Sleeping for 30 seconds"
sleep 30
pushd ../../agent_codes
    bash build_companyagents_and_push.bash
popd

bash $CUR_DIR/unregister-agents.sh
sleep 2
bash $CUR_DIR/register-agents.sh
sleep 2
bash $CUR_DIR/deploy-agents.sh

echo "All-in-One Setup Complete."
