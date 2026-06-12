#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "[log-detective] Building tool.zip (code/)..."
rm -f tool.zip agent-tool.zip
zip -r tool.zip code/

echo "[log-detective] Building agent-tool.zip (spec.json + tool.md + tool.zip)..."
zip agent-tool.zip spec.json tool.md tool.zip

echo "[log-detective] Done: $(du -sh agent-tool.zip | cut -f1) -> agent-tool.zip"
