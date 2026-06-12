#!/bin/bash
# Upload the three function bundles to the functions registry.
# Each .zip contains function.json + function.zip (the code).

#!/bin/bash

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
FUNCTIONS_DIR="$(cd "$(dirname "$0")/functions" && pwd)"

echo "=== Uploading code-validator ==="
curl -sS -X POST "$FUNCTIONS_UPLOAD" \
  -F "file=@${FUNCTIONS_DIR}/code-validator/code-validator.zip;type=application/zip" | jq

echo ""
echo "=== Uploading test-case-generator ==="
curl -sS -X POST "$FUNCTIONS_UPLOAD" \
  -F "file=@${FUNCTIONS_DIR}/test-case-generator/test-case-generator.zip;type=application/zip" | jq

echo ""
echo "=== Uploading test-runner ==="
curl -sS -X POST "$FUNCTIONS_UPLOAD" \
  -F "file=@${FUNCTIONS_DIR}/test-runner/test-runner.zip;type=application/zip" | jq

echo ""
echo "Upload complete."
echo "Function URIs:"
echo "  code-validator:1.0.0-stable"
echo "  test-case-generator:1.0.0-stable"
echo "  test-runner:1.0.0-stable"

