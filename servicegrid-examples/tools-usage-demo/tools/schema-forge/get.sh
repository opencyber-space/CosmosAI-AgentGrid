#!/bin/bash
TOOLS_URL="${TOOLS_URL:-http://x.x.x.x:30702}"
curl -s -X GET "$TOOLS_URL/tools/agentspace.schema-forge.v4" | jq
