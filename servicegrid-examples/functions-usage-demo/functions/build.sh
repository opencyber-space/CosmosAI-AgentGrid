#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 1. code-validator
echo "[build] Building code-validator..."
cd "$SCRIPT_DIR/functions/code-validator/function"
rm -f function.zip
zip -r function.zip code/
mv function.zip ../
cd "$SCRIPT_DIR/functions/code-validator"
rm -f code-validator.zip
zip code-validator.zip function.json function.zip

# 2. test-case-generator
echo "[build] Building test-case-generator..."
cd "$SCRIPT_DIR/functions/test-case-generator/function"
rm -f function.zip
zip -r function.zip code/
mv function.zip ../
cd "$SCRIPT_DIR/functions/test-case-generator"
rm -f test-case-generator.zip
zip test-case-generator.zip function.json function.zip

# 3. test-runner
echo "[build] Building test-runner..."
cd "$SCRIPT_DIR/functions/test-runner/function"
rm -f function.zip
zip -r function.zip code/
mv function.zip ../
cd "$SCRIPT_DIR/functions/test-runner"
rm -f test-runner.zip
zip test-runner.zip function.json function.zip

echo "[build] All builds completed successfully."
