#!/bin/bash

GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$GIT_ROOT" ]; then
    GIT_ROOT=$(pwd) # Fallback if not run within git
fi
if [ -f "$GIT_ROOT/.env" ]; then
    set -a; source "$GIT_ROOT/.env"; set +a
else
    echo "Error: .env file MUST be present at $GIT_ROOT"
    exit 1
fi

curl -X POST ${POLICY_DB_URL}/policy \
     -H "Content-Type: application/json" \
     -d '{
           "name": "test-case-generator",
           "version": "1.1",
           "release_tag": "stable",
           "metadata": {"author": "admin", "category": "code-analysis"},
           "tags": "code-analysis,openai,testing",
           "code": "'${POLICY_UPLOAD_URL}'/test-gen-01.zip",
           "code_type": "dir",
           "type": "policy",
           "policy_input_schema": {
             "type": "object",
             "properties": {
               "code":            {"type": "string"},
               "function_name":   {"type": "string"},
               "description":     {"type": "string"},
               "code_validation": {"type": "object"}
             },
             "required": ["code", "function_name"]
           },
           "policy_output_schema": {
             "type": "object",
             "properties": {
               "code":            {"type": "string"},
               "function_name":   {"type": "string"},
               "description":     {"type": "string"},
               "code_validation": {"type": "object"},
               "test_cases": {
                 "type": "array",
                 "items": {
                   "type": "object",
                   "properties": {
                     "description":     {"type": "string"},
                     "inputs":          {"type": "object"},
                     "expected_output": {}
                   }
                 }
               }
             }
           },
           "policy_settings_schema": {},
           "policy_parameters_schema": {
             "openai_api_key": {"type": "string"},
             "model":          {"type": "string"},
             "num_tests":      {"type": "integer"}
           },
           "policy_settings": {
              "openai_api_key": "<api-key-here>"
           },
           "policy_parameters": {
             "openai_api_key": "<api-key-here>",
             "model": "gpt-4o-mini",
             "num_tests": 3
           },
           "description": "Generates test inputs and expected outputs for a Python function using OpenAI. Expects input_data enriched by policy1 (code_validation pass-through). Adds test_cases for policy3.",
           "functionality_data": {"strategy": "openai-test-generation"},
           "resource_estimates": {}
         }'
