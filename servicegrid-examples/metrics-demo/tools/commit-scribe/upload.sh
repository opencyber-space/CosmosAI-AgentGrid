#!/bin/bash
# Upload commit-scribe to the tools service
set -e

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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -f "$SCRIPT_DIR/agent-tool.zip" ]; then
  echo "[commit-scribe] agent-tool.zip not found — running build first..."
  bash "$SCRIPT_DIR/build.sh"
fi

echo "Deleting the registered commit-scribe tool"
bash "$SCRIPT_DIR/delete.sh"

echo "[commit-scribe] Uploading to ${TOOLS_REGISTRY_URL}/tools/upload ..."
curl -s -X POST "${TOOLS_REGISTRY_URL}/tools/upload" \
  -H "Accept: application/json" \
  -F "file=@$SCRIPT_DIR/agent-tool.zip;type=application/zip" | jq
