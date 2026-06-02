#!/bin/bash

# Get directory of current script
CUR_DIR=$(dirname "$(realpath "$0")")

echo "=========================================================="
echo "Registering ALL Hierarchical Workflows..."
echo "=========================================================="

echo -e "\n---> Executing register_workflow_architectureteam.sh..."
bash "$CUR_DIR/register_workflow_architectureteam.sh"

echo -e "\n---> Executing register_workflow_developerteam.sh..."
bash "$CUR_DIR/register_workflow_developerteam.sh"

echo -e "\n---> Executing register_workflow_financeteam.sh..."
bash "$CUR_DIR/register_workflow_financeteam.sh"

echo -e "\n---> Executing register_workflow_marketingteam.sh..."
bash "$CUR_DIR/register_workflow_marketingteam.sh"

echo -e "\n---> Executing register_workflow_testingteam.sh..."
bash "$CUR_DIR/register_workflow_testingteam.sh"

echo -e "\n---> Executing register_workflow_cos.sh..."
bash "$CUR_DIR/register_workflow_cos.sh"

echo -e "\n---> Executing register_workflow_final.sh..."
bash "$CUR_DIR/register_workflow_final.sh"

echo -e "\n=========================================================="
echo "All Hierarchical Workflows registered successfully."
echo "=========================================================="
