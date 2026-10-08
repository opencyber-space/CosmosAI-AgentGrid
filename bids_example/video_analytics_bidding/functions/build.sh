#!/bin/bash
set -e

# Packages each function as the registry expects: an outer zip of function.json plus
# function.zip, where function.zip holds code/.
#
# va-bid-eval additionally vendors the shared scoring maths and the registry client.
# The registry runs function/code/ as an isolated tree with no access to the repo, so
# `import va_bid_utils` / `from agents_functions import AgentFunctions` would fail at
# run time without this copy. Re-copying on every build is what stops the vendored
# copies drifting from the originals.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIDS_EXAMPLE="$(cd "$SCRIPT_DIR/../.." && pwd)"

# A function.json may carry ${VAR} placeholders for anything deployment-specific, so the
# repo holds no cluster's IP addresses. They are expanded into the packaged copy only.
# va-bid-eval needs this: it reads functions_registry_url from its own settings to call
# the companies' live endpoints, and with the setting absent it logs
# "FUNCTION_REGISTRY_URL is unset; endpoint dimension scores 0" and quietly scores that
# whole dimension zero for everyone -- which is what round 9 did.
GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo "$BIDS_EXAMPLE/..")
if [ -f "$GIT_ROOT/.env" ]; then
    set -a; source "$GIT_ROOT/.env"; set +a
else
    echo "[build] Error: .env not found at $GIT_ROOT" >&2; exit 1
fi

package() {
    local name="$1"
    echo "[build] Building ${name}..."
    cd "$SCRIPT_DIR/${name}/function"
    rm -f function.zip
    find . -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
    zip -qr function.zip code/
    mv function.zip ../
    cd "$SCRIPT_DIR/${name}"
    rm -f "${name}.zip"

    local staged
    staged=$(mktemp -d)
    envsubst < function.json > "$staged/function.json"
    if grep -q '\${' "$staged/function.json"; then
        echo "[build] Error: unexpanded placeholder left in ${name}/function.json --" >&2
        grep -n '\${' "$staged/function.json" >&2
        rm -rf "$staged"; exit 1
    fi
    python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$staged/function.json" || {
        echo "[build] Error: ${name}/function.json is not valid JSON after expansion" >&2
        rm -rf "$staged"; exit 1; }
    cp function.zip "$staged/function.zip"
    ( cd "$staged" && zip -q "${name}.zip" function.json function.zip )
    mv "$staged/${name}.zip" "./${name}.zip"
    rm -rf "$staged"
    echo "[build]   -> ${name}/${name}.zip"
}

# Both functions OpenArcade calls report to HIS, so their reasoning is visible in the
# dashboard rather than only in a pod log. Same reason as the vendoring below: the
# registry runs function/code/ as an isolated tree, so `import function_his` needs a
# copy inside each package.
echo "[build] Vendoring function_his into va-bidding-pqt and va-bid-eval..."
for target in va-bidding-pqt va-bid-eval; do
    cp "$SCRIPT_DIR/common/function_his.py" "$SCRIPT_DIR/$target/function/code/function_his.py"
done
echo "[build]   -> function_his.py x2"

echo "[build] Vendoring shared code into va-bid-eval..."
cp "$BIDS_EXAMPLE/utils/va_bid_utils.py" "$SCRIPT_DIR/va-bid-eval/function/code/va_bid_utils.py"
rm -rf "$SCRIPT_DIR/va-bid-eval/function/code/agents_functions"
mkdir -p "$SCRIPT_DIR/va-bid-eval/function/code/agents_functions"
cp "$BIDS_EXAMPLE"/agents_functions/*.py "$SCRIPT_DIR/va-bid-eval/function/code/agents_functions/"
echo "[build]   -> va_bid_utils.py + agents_functions/"

# va-rfp-requirements scopes the extracted list itself, so every company sees the same
# filtering. Same reason as above: the registry runs function/code/ as an isolated tree.
echo "[build] Vendoring rfp_scope into va-rfp-requirements..."
cp "$SCRIPT_DIR/../nodes/common/rfp_scope.py" \
   "$SCRIPT_DIR/va-rfp-requirements/function/code/rfp_scope.py"
echo "[build]   -> rfp_scope.py"

package va-bidding-pqt
package va-bid-eval
package va-rfp-requirements

# The live endpoints are no longer cloned by the agents mid-round. One package is built
# here per company per use case it declares under live_endpoints.endpoints, capped by
# its own max_live_endpoints. Each one carries that company's answers from the
# uncommitted verdicts/<slug>_verdicts.yaml, copied into code/ for the zip and deleted
# straight after; a company with no such file still gets an endpoint, which answers
# false to everything and scores 0.
echo "[build] Building per-company live endpoints..."
PYTHON="$GIT_ROOT/venv/bin/python"
[ -x "$PYTHON" ] || PYTHON=python3
"$PYTHON" "$SCRIPT_DIR/build_endpoints.py"

echo "[build] All builds completed successfully."
