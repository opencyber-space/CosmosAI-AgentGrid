#!/bin/bash
# Launch the bidding dashboard. Read-only: it inspects a round, it does not run one.

GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
[ -z "$GIT_ROOT" ] && GIT_ROOT=$(pwd)
if [ -f "$GIT_ROOT/.env" ]; then
    set -a; source "$GIT_ROOT/.env"; set +a
else
    echo "Error: .env file MUST be present at $GIT_ROOT" >&2; exit 1
fi

SCRIPT_DIR=$(dirname "$(realpath "$0")")
PORT="${VA_STREAMLIT_PORT:-8008}"   # 8007 is the bids_processing dashboard

exec "$GIT_ROOT/venv/bin/streamlit" run "$SCRIPT_DIR/streamlit_app.py" --server.port "$PORT"
