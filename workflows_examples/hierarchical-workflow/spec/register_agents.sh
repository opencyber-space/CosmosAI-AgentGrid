#!/bin/bash

# Get directory of current script
CUR_DIR=$(dirname "$(realpath "$0")")

echo "=========================================================="
echo "Registering ALL Hierarchical Workflow Agents..."
echo "=========================================================="

echo -e "\n---> Executing register_architecture_agents.sh..."
bash "$CUR_DIR/register_architecture_agents.sh"

echo -e "\n---> Executing register_developer_agents.sh..."
bash "$CUR_DIR/register_developer_agents.sh"

echo -e "\n---> Executing register_finanace_agents.sh..."
bash "$CUR_DIR/register_finanace_agents.sh"

echo -e "\n---> Executing register_marketing_agents.sh..."
bash "$CUR_DIR/register_marketing_agents.sh"

echo -e "\n---> Executing register_testing_agents.sh..."
bash "$CUR_DIR/register_testing_agents.sh"

echo -e "\n---> Executing register_cos_agents.sh..."
bash "$CUR_DIR/register_cos_agents.sh"

echo -e "\n---> Executing register_ceo_agents.sh..."
bash "$CUR_DIR/register_ceo_agents.sh"

echo -e "\n=========================================================="
echo "All Hierarchical Workflow Agents registered successfully."
echo "=========================================================="
