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
           "name": "code-validator",
           "version": "1.1",
           "release_tag": "stable",
           "metadata": {"author": "admin", "category": "code-analysis"},
           "tags": "code-analysis,openai,validation",
           "code": "'${POLICY_UPLOAD_URL}'/validator01.zip",
           "code_type": "dir",
           "type": "policy",
           "policy_input_schema": {
             "type": "object",
             "properties": {
               "code":          {"type": "string"},
               "function_name": {"type": "string"},
               "description":   {"type": "string"}
             },
             "required": ["code", "function_name"]
           },
           "policy_output_schema": {
             "type": "object",
             "properties": {
               "code":            {"type": "string"},
               "function_name":   {"type": "string"},
               "description":     {"type": "string"},
               "code_validation": {
                 "type": "object",
                 "properties": {
                   "is_valid":       {"type": "boolean"},
                   "issues":         {"type": "array", "items": {"type": "string"}},
                   "optimizations":  {"type": "array", "items": {"type": "string"}},
                   "optimized_code": {"type": "string"}
                 }
               }
             }
           },
           "policy_settings_schema": {},
           "policy_parameters_schema": {
             "openai_api_key": {"type": "string"},
             "model":          {"type": "string"}
           },
           "policy_settings": {
              "openai_api_key": "<api-key-here>"
           },
           "policy_parameters": {
             "openai_api_key": "<api-key-here>",
             "model": "gpt-4o-mini"
           },
           "description": "Validates Python code correctness and suggests optimizations using OpenAI. Pass-through enriches input_data with code_validation for downstream policies.",
           "functionality_data": {"strategy": "openai-code-review"},
           "resource_estimates": {}
         }'
