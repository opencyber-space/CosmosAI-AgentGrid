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
           "name": "test-runner",
           "version": "1.0",
           "release_tag": "stable",
           "metadata": {"author": "admin", "category": "code-analysis"},
           "tags": "code-analysis,testing,executor",
           "code": "'${POLICY_UPLOAD_URL}'/runner-01.zip",
           "code_type": "dir",
           "type": "policy",
           "policy_input_schema": {
             "type": "object",
             "properties": {
               "code":            {"type": "string"},
               "function_name":   {"type": "string"},
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
             },
             "required": ["code", "function_name", "test_cases"]
           },
           "policy_output_schema": {
             "type": "object",
             "properties": {
               "code_validation": {"type": "object"},
               "test_inputs": {
                 "type": "array",
                 "items": {
                   "type": "object",
                   "properties": {
                     "description": {"type": "string"},
                     "inputs":      {"type": "object"}
                   }
                 }
               },
               "test_results": {
                 "type": "array",
                 "items": {
                   "type": "object",
                   "properties": {
                     "status":          {"type": "string"},
                     "description":     {"type": "string"},
                     "inputs":          {"type": "object"},
                     "expected_output": {},
                     "actual_output":   {},
                     "passed":          {"type": "boolean"},
                     "error":           {"type": "string"}
                   }
                 }
               },
               "summary": {
                 "type": "object",
                 "properties": {
                   "total":  {"type": "integer"},
                   "passed": {"type": "integer"},
                   "failed": {"type": "integer"}
                 }
               }
             }
           },
           "policy_settings_schema": {},
           "policy_parameters_schema": {},
           "policy_settings": {},
           "policy_parameters": {},
           "description": "Executes test cases against the submitted code using exec(). Reads code_validation (policy1) and test_cases (policy2) from the enriched input_data and returns all three results combined.",
           "functionality_data": {"strategy": "local-exec"},
           "resource_estimates": {}
         }'
