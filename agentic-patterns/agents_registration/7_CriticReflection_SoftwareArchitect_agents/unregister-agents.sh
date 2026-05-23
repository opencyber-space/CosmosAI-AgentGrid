#!/bin/bash

# Get the directory where this script is located
CUR_DIR=$(dirname "$(realpath "$0")")

echo "Unregistering Architecture Debater Agents..."

bash $CUR_DIR/software-agent/unregister_agent.sh
bash $CUR_DIR/senior-architect-agent/unregister_agent.sh

echo "All Architecture Debater agents unregistered."
