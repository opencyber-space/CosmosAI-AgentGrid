#!/bin/bash

# Get the directory where this script is located
CUR_DIR=$(dirname "$(realpath "$0")")

echo "Removing Architecture Debater Agents..."

bash $CUR_DIR/software-agent/remove-agent.sh
bash $CUR_DIR/senior-architect-agent/remove-agent.sh

echo "All Architecture Debater agents removed."
