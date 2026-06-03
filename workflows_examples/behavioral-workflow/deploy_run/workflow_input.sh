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


# Fetch the workflow execution URL
RESPONSE=$(curl -s "${API_BASE_URL}/api/runtime-workflows?workflow_uri=simple-behavioral-workflow:1.0.0-stable&limit=20&skip=0")
WORKFLOW_URL=$(echo "$RESPONSE" | python3 -c 'import sys, json; print(json.load(sys.stdin)["data"][0]["url"])')

if [ -z "$WORKFLOW_URL" ]; then
    echo "Error: Could not retrieve workflow URL from response: $RESPONSE"
    exit 1
fi

echo "Executing workflow at $WORKFLOW_URL"

echo "Running Example 1 (Square Root Sum):"
curl -X POST "$WORKFLOW_URL/api/execute" -H "Content-Type: application/json" \
-d '{
  "user_request": "Create a function for adding 2 numbers squareroot i.e if i send 4, 9 then sum is 2+3=5 as 2 is square root of 4. Make sure the code generated is just a single function."
}' | json_pp

echo "--------------------------------------------------------"

echo "Running Example 2 (Anagram Check):"
# To run Example 2 instead, uncomment the lines below and comment out Example 1
# curl -X POST "$WORKFLOW_URL/api/execute" -H "Content-Type: application/json" \
# -d '{
#   "user_request": "Create a function that checks if a string is an anagram of another string. It should ignore capitalization and spaces. Make sure all code generated gets over in a single function only."
# }' | json_pp