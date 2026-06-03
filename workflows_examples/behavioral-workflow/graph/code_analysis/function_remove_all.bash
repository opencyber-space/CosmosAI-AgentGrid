#!/bin/bash
GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$GIT_ROOT" ]; then GIT_ROOT=$(pwd); fi
if [ -f "$GIT_ROOT/.env" ]; then set -a; source "$GIT_ROOT/.env"; set +a; else echo "Error: .env file MUST be present at $GIT_ROOT"; exit 1; fi

FUNCTIONS=(
    "function1.sh"
    "function2.sh"
    "function3.sh"
)

DIR="$(dirname "$0")"

for FUNC_SCRIPT in "${FUNCTIONS[@]}"; do
    SCRIPT_PATH="$DIR/$FUNC_SCRIPT"
    if [ -f "$SCRIPT_PATH" ]; then
        echo "Processing $FUNC_SCRIPT..."
        
        # Safely extract name using python3 and regex
        NAME=$(python3 -c "import sys, re; match = re.search(r'\"name\":\s*\"([^\"]+)\"', sys.stdin.read()); print(match.group(1)) if match else ''" < "$SCRIPT_PATH")
        
        if [ -n "$NAME" ]; then
            echo "Removing function deployment ${NAME}..."
            curl -s -X DELETE "${POLICY_DB_URL}/function/deployments/remove/${NAME}" | json_pp
            echo -e "\nRemoval completed for $FUNC_SCRIPT"
        else
            echo "Warning: 'name' not found in $FUNC_SCRIPT, skipping..."
        fi
    else
        echo "Warning: Script $FUNC_SCRIPT does not exist, skipping..."
    fi
done