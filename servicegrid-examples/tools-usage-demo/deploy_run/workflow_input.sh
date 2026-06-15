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
RESPONSE=$(curl -s "${API_BASE_URL}/api/runtime-workflows?workflow_uri=simple-tool-usage-workflow:1.0.0-stable&limit=20&skip=0")
WORKFLOW_URL=$(echo "$RESPONSE" | python3 -c 'import sys, json; print(json.load(sys.stdin)["data"][0]["url"])')

if [ -z "$WORKFLOW_URL" ]; then
    echo "Error: Could not retrieve workflow URL from response: $RESPONSE"
    exit 1
fi

echo "Executing workflow at $WORKFLOW_URL"

echo "Running Example 1 (Commit Scribe):"

diff='diff --git a/auth/login.py b/auth/login.py
index 3a1f2b4..9c8d1e5 100644
--- a/auth/login.py
+++ b/auth/login.py
@@ -10,6 +10,10 @@ def login(request):
     token = request.headers.get("Authorization")
+    if not token:
+        raise AuthError("missing token")
+    if len(token) < 32:
+        raise AuthError("token too short")
     user = verify_token(token)
     return user
'

payload=$(jq -n --arg diff "$diff" '{user_request: $diff}')
echo "$payload"

curl -X POST "$WORKFLOW_URL/api/execute" -H "Content-Type: application/json" \
-d "$payload" | json_pp

echo "--------------------------------------------------------"

echo "Running Example 2 (Log Detective):"

logs='2024-06-10T02:14:01Z INFO  payments-api: request received POST /charge
2024-06-10T02:14:01Z ERROR db: connection timeout after 30s (attempt 1/3)
2024-06-10T02:14:02Z WARN  payments-api: retrying db connection
2024-06-10T02:14:32Z ERROR db: connection timeout after 30s (attempt 2/3)
2024-06-10T02:14:33Z ERROR db: connection timeout after 30s (attempt 3/3)
2024-06-10T02:14:33Z FATAL payments-api: circuit breaker OPEN — db unreachable
2024-06-10T02:14:34Z ERROR payments-api: returning 503 to client
'

payload=$(jq -n --arg logs "$logs" '{user_request: $logs}')
echo "$payload"

curl -X POST "$WORKFLOW_URL/api/execute" -H "Content-Type: application/json" \
-d "$payload" | json_pp

echo "--------------------------------------------------------"

# To run Example 2 instead, uncomment the lines below and comment out Example 1
# curl -X POST "$WORKFLOW_URL/api/execute" -H "Content-Type: application/json" \
# -d '{
#   "user_request": "Create a function that checks if a string is an anagram of another string. It should ignore capitalization and spaces. Make sure all code generated gets over in a single function only."
# }' | json_pp