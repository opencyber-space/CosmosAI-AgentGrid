#!/bin/bash
# Build agent-tool.zip for commit-scribe (mirrors sample/ layout)
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "[commit-scribe] Building tool.zip (code/)..."
rm -f tool.zip agent-tool.zip
zip -r tool.zip code/

echo "[commit-scribe] Building agent-tool.zip (spec.json + tool.md + tool.zip)..."
zip agent-tool.zip spec.json tool.md tool.zip

echo "[commit-scribe] Done: $(du -sh agent-tool.zip | cut -f1) -> agent-tool.zip"
