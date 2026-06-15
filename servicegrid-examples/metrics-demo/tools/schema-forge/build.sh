#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "[schema-forge] Building tool.zip (code/)..."
rm -f tool.zip agent-tool.zip
zip -r tool.zip code/

echo "[schema-forge] Building agent-tool.zip (spec.json + tool.md + tool.zip)..."
zip agent-tool.zip spec.json tool.md tool.zip

echo "[schema-forge] Done: $(du -sh agent-tool.zip | cut -f1) -> agent-tool.zip"
