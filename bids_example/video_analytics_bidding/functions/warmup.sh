#!/bin/bash
set -e

# Wrapper around warmup.py: loads .env and uses the repo venv.
#
# Run this after upload.sh and before any round. See warmup.py for why -- in short, the
# first caller of a freshly uploaded stateful function pays for a container start and a
# pip install, and neither OpenArcade's 60-second evaluator budget nor a compliance
# agent's call survives that.

GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
[ -z "$GIT_ROOT" ] && GIT_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"

if [ -f "$GIT_ROOT/.env" ]; then
    set -a; source "$GIT_ROOT/.env"; set +a
else
    echo "Error: .env not found at $GIT_ROOT" >&2; exit 1
fi

PYTHON="$GIT_ROOT/venv/bin/python"
[ -x "$PYTHON" ] || PYTHON=python3

FUNCTIONS_DIR="$(cd "$(dirname "$0")" && pwd)"
VERDICTS_DIR="${FUNCTIONS_DIR}/va-usecase-endpoint/verdicts"

# --------------------------------------------------------------------------
# Each company's live endpoints answer from a file that is NOT in this repo.
#
# An answer key committed beside the company being graded on it is not a benchmark, so
# verdicts/<slug>_verdicts.yaml is gitignored and every machine keeps its own. build.sh
# packages whatever is here into that company's endpoints; nothing here means that
# company answers false to every image and scores 0 on the endpoint dimension. That is
# the safe direction -- the dimension is absolute, so 0 for everyone adds 0 to every
# total and the live bake-off simply drops out of the ranking, where a default of true
# would hand all five a perfect score and hide the misconfiguration.
#
# The format, one file per company, keys matching live_endpoints.endpoints in that
# company's nodes/<Company>/config.yaml:
#
#     # functions/va-usecase-endpoint/verdicts/camfacesolution_verdicts.yaml
#     face_recognition:
#       face_01.png: true
#       face_02.png: true     # ground truth false -- this company gets it wrong
#       ...
#     crowd_multiface:
#       face_01.png: true
#       ...
#
# The image names and the ground truth they are scored against are in
# deploy_run/seed_eval_images.py, and the ground truth also travels on the bid job so a
# reviewer can check the scoring by hand.
# --------------------------------------------------------------------------
MISSING=""
for config in "$FUNCTIONS_DIR"/../nodes/*/config.yaml; do
    [ -f "$config" ] || continue
    company=$(basename "$(dirname "$config")")
    slug=$(echo "$company" | tr "[:upper:]" "[:lower:]")
    [ -f "${VERDICTS_DIR}/${slug}_verdicts.yaml" ] || MISSING="$MISSING $company"
done
if [ -n "$MISSING" ]; then
    echo "=========================================================="
    echo "No endpoint answers for:$MISSING"
    echo ""
    echo "Those companies' endpoints will answer false to every image and score 0."
    echo "To give one answers, create:"
    echo "    ${VERDICTS_DIR}/<company-in-lowercase>_verdicts.yaml"
    echo "then re-run build.sh and upload.sh. The format is documented at the top of"
    echo "this script; the image names come from deploy_run/seed_eval_images.py."
    echo "=========================================================="
    echo ""
fi

exec "$PYTHON" "$FUNCTIONS_DIR/warmup.py"
