#!/bin/bash

# Get the directory where this script is located
CUR_DIR=$(dirname "$(realpath "$0")")

echo "Registering Architecture Debater Agents..."

bash $CUR_DIR/software-agent/register_agent.sh
bash $CUR_DIR/senior-architect-agent/register_agent.sh

echo "All Architecture Debater agents registered."
