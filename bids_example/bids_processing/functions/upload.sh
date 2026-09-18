#!/bin/bash
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

FUNCTIONS_UPLOAD="${FUNCTION_UPLOAD_URL}/functions/upload"
FUNCTIONS_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Deleting existing functions ==="
bash "$FUNCTIONS_DIR/delete.sh"

echo "=== Uploading dummy-pqt ==="
curl -sS -X POST "$FUNCTIONS_UPLOAD" \
  -F "file=@${FUNCTIONS_DIR}/dummy-pqt/dummy-pqt.zip;type=application/zip" | jq || true

echo ""
echo "=== Uploading bids-evaluator ==="
curl -sS -X POST "$FUNCTIONS_UPLOAD" \
  -F "file=@${FUNCTIONS_DIR}/bids-evaluator/bids-evaluator.zip;type=application/zip" | jq || true

echo ""
echo "Upload complete."
echo "Function URIs:"
echo "  dummy-pqt:1.0-stable"
echo "  bids-evaluator:1.0-stable"
