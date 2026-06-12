#!/bin/bash
set -e
TOOLS_URL="${TOOLS_URL:-http://x.x.x.x:30702}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -f "$SCRIPT_DIR/agent-tool.zip" ]; then
  echo "[schema-forge] agent-tool.zip not found — running build first..."
  bash "$SCRIPT_DIR/build.sh"
fi

echo "[schema-forge] Uploading to $TOOLS_URL/tools/upload ..."
curl -s -X POST "$TOOLS_URL/tools/upload" \
  -H "Accept: application/json" \
  -F "file=@$SCRIPT_DIR/agent-tool.zip;type=application/zip" | jq
