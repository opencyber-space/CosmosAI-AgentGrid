#!/bin/bash
GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$GIT_ROOT" ]; then GIT_ROOT=$(pwd); fi
if [ -f "$GIT_ROOT/.env" ]; then set -a; source "$GIT_ROOT/.env"; set +a; else echo "Error: .env file MUST be present at $GIT_ROOT"; exit 1; fi

FUNCTIONS=(
    "function1_registration_test_gen.sh"
    "function2_registration_validator.sh"
    "function3_registration_runner.sh"
)

DIR="$(dirname "$0")"

for FUNC_SCRIPT in "${FUNCTIONS[@]}"; do
    SCRIPT_PATH="$DIR/$FUNC_SCRIPT"
    if [ -f "$SCRIPT_PATH" ]; then
        echo "Processing $FUNC_SCRIPT..."
        
        # Safely extract name, version, and release_tag using python3 and regex
        NAME=$(python3 -c "import sys, re; data=sys.stdin.read(); m=re.search(r'\"name\":\s*\"([^\"]+)\"', data); print(m.group(1)) if m else ''" < "$SCRIPT_PATH")
        VERSION=$(python3 -c "import sys, re; data=sys.stdin.read(); m=re.search(r'\"version\":\s*\"([^\"]+)\"', data); print(m.group(1)) if m else ''" < "$SCRIPT_PATH")
        RELEASE_TAG=$(python3 -c "import sys, re; data=sys.stdin.read(); m=re.search(r'\"release_tag\":\s*\"([^\"]+)\"', data); print(m.group(1)) if m else ''" < "$SCRIPT_PATH")
        
        if [ -n "$NAME" ] && [ -n "$VERSION" ] && [ -n "$RELEASE_TAG" ]; then
            echo "Unregistering ${NAME}:${VERSION}-${RELEASE_TAG}..."
            curl -s -X DELETE "${POLICY_DB_URL}/policy/${NAME}:${VERSION}-${RELEASE_TAG}" | json_pp
            echo -e "\nUnregistration completed for $FUNC_SCRIPT"
        else
            echo "Warning: Missing name, version, or release_tag in $FUNC_SCRIPT, skipping..."
        fi
    else
        echo "Warning: Script $FUNC_SCRIPT does not exist, skipping..."
    fi
done