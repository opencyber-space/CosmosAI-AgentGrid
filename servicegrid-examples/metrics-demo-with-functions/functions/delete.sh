#!/bin/bash
# Delete the three functions from the functions registry.

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

if [ -z "$FUNCTION_REGISTRY_URL" ]; then
    echo "Error: FUNCTION_REGISTRY_URL is not set in .env"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Array of JSON files relative to SCRIPT_DIR
JSON_FILES=(
    "functions/code-validator/function.json"
    "functions/test-case-generator/function.json"
    "functions/test-runner/function.json"
)

for relative_path in "${JSON_FILES[@]}"; do
    json_path="${SCRIPT_DIR}/${relative_path}"
    if [ ! -f "$json_path" ]; then
        echo "Error: JSON file not found at $json_path"
        continue
    fi

    # Read keys using python
    read -r name version tag <<< $(python3 -c "import json, sys; d=json.load(open(sys.argv[1])); print(d.get('function_name', ''), d.get('function_version', ''), d.get('function_release_tag', ''))" "$json_path")

    if [ -z "$name" ] || [ "$name" == "null" ] || [ -z "$version" ] || [ "$version" == "null" ] || [ -z "$tag" ] || [ "$tag" == "null" ]; then
        echo "Error: Failed to parse function metadata from $json_path"
        continue
    fi

    function_id="${name}:${version}-${tag}"
    echo "=== Deleting function: $function_id ==="
    curl -sS -X DELETE "${FUNCTION_REGISTRY_URL}/functions/${function_id}"
    echo ""
done

echo "Delete process complete."
