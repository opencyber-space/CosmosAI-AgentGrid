#!/bin/bash

# Get the directory where this script is located
CUR_DIR=$(dirname "$(realpath "$0")")

echo "Deploying Architecture Debater Agents..."

bash $CUR_DIR/software-agent/deploy-agent.sh
bash $CUR_DIR/senior-architect-agent/deploy-agent.sh

echo "All Architecture Debater agents deployed."
