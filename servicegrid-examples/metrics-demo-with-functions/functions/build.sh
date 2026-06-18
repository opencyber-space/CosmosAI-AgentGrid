#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Helper to copy dependencies into a function's code directory
copy_deps() {
    local target_dir="$1"
    echo "[build] Copying metrics dependencies to $target_dir"
    cp "$SCRIPT_DIR/../../utils/metrics_util.py" "$target_dir/"
    cp "$SCRIPT_DIR/../../agents_sdk/core/metrics.py" "$target_dir/"
}

# Helper to clean up dependencies
clean_deps() {
    local target_dir="$1"
    echo "[build] Cleaning metrics dependencies from $target_dir"
    rm -f "$target_dir/metrics_util.py"
    rm -f "$target_dir/metrics.py"
}

# 1. code-validator
echo "[build] Building code-validator..."
copy_deps "$SCRIPT_DIR/functions/code-validator/function/code"
cd "$SCRIPT_DIR/functions/code-validator/function"
rm -f function.zip
zip -r function.zip code/
mv function.zip ../
clean_deps "$SCRIPT_DIR/functions/code-validator/function/code"
cd "$SCRIPT_DIR/functions/code-validator"
rm -f code-validator.zip
zip code-validator.zip function.json function.zip

# 2. test-case-generator
echo "[build] Building test-case-generator..."
copy_deps "$SCRIPT_DIR/functions/test-case-generator/function/code"
cd "$SCRIPT_DIR/functions/test-case-generator/function"
rm -f function.zip
zip -r function.zip code/
mv function.zip ../
clean_deps "$SCRIPT_DIR/functions/test-case-generator/function/code"
cd "$SCRIPT_DIR/functions/test-case-generator"
rm -f test-case-generator.zip
zip test-case-generator.zip function.json function.zip

# 3. test-runner
echo "[build] Building test-runner..."
copy_deps "$SCRIPT_DIR/functions/test-runner/function/code"
cd "$SCRIPT_DIR/functions/test-runner/function"
rm -f function.zip
zip -r function.zip code/
mv function.zip ../
clean_deps "$SCRIPT_DIR/functions/test-runner/function/code"
cd "$SCRIPT_DIR/functions/test-runner"
rm -f test-runner.zip
zip test-runner.zip function.json function.zip

echo "[build] All builds completed successfully."

