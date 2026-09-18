#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 1. dummy-pqt
echo "[build] Building dummy-pqt..."
cd "$SCRIPT_DIR/dummy-pqt/function"
rm -f function.zip
zip -r function.zip code/
mv function.zip ../
cd "$SCRIPT_DIR/dummy-pqt"
rm -f dummy-pqt.zip
zip dummy-pqt.zip function.json function.zip

# 2. bids-evaluator
echo "[build] Building bids-evaluator..."
cd "$SCRIPT_DIR/bids-evaluator/function"
rm -f function.zip
zip -r function.zip code/
mv function.zip ../
cd "$SCRIPT_DIR/bids-evaluator"
rm -f bids-evaluator.zip
zip bids-evaluator.zip function.json function.zip

echo "[build] All builds completed successfully."
