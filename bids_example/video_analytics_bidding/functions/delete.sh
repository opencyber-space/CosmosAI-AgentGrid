#!/bin/bash

# Removes the shared functions AND every per-company va-uc-* endpoint.
#
# The endpoints matter most here. They are keyed by function_id, so a re-upload
# overwrites them -- but if a company's answers changed between rounds and the old
# function is still registered under a name the new upload does not re-register, the
# evaluator would score against a stale map and nobody would notice. Since the answers
# now ride inside the code zip, a changed verdicts/<slug>_verdicts.yaml produces a new
# artifact that only reaches a pod once the deployment is gone -- which is what the
# deployment removal below is for.

GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$GIT_ROOT" ]; then
    GIT_ROOT=$(pwd)
fi
if [ -f "$GIT_ROOT/.env" ]; then
    set -a; source "$GIT_ROOT/.env"; set +a
else
    echo "Error: .env file MUST be present at $GIT_ROOT"
    exit 1
fi

if [ -z "$FUNCTION_REGISTRY_URL" ]; then
    echo "Error: FUNCTION_REGISTRY_URL is not set in .env"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

delete_one() {
    echo "=== Deleting function: $1 ==="
    curl -sS -X DELETE "${FUNCTION_REGISTRY_URL}/functions/$1" | jq || true
    echo ""
}

# The endpoints are stateful, so deleting the function leaves its deployment running.
# That pod would then answer the NEXT round with the PREVIOUS round's answers,
# because the SDK reuses a deployment it finds by name instead of replacing it. Deleting
# the function without the deployment is therefore worse than not deleting at all.
#
# The deployment id is what AgentFunctions composes: "{function_name}-{unique_parameter}",
# and DEPLOYMENT_SCOPE in nodes/common/function_publisher.py is the unique_parameter.
DEPLOYMENT_SCOPE="va-live"
# OpenArcade runs the PQT and the evaluator under its own scope, so their deployments
# are named "<function>-orcade". They are just as stale-prone as the endpoints: leaving
# va-bid-eval-orcade running means the next round is scored by the previous upload.
ORCADE_SCOPE="orcade"

# Versions no longer named by any bid job, but whose deployments may still be up.
RETIRED_TAGS="1.0-stable 1.1-stable 1.2-stable 1.3-stable"
# The function_id in the body has to be the one the deployment was actually created
# from, not a guess. This used to hardcode ":1.0-stable", which quietly did nothing for
# any deployment created from a later version: va-bid-eval-orcade survived a delete,
# warmup found it already serving and returned in 1s, and the round was then scored by a
# five-hour-old pod running the previous upload -- no error anywhere, just a function
# that did not do the new thing. Every known version is tried, so whichever one the
# deployment holds is the one that matches.
known_versions() {
    # known_versions <function_name> -> the manifest's version first, then the retired ones
    local manifest="${SCRIPT_DIR}/$1/function.json"
    if [ -f "$manifest" ]; then
        jq -r '"\(.function_version)-\(.function_release_tag)"' "$manifest"
    fi
    printf '%s\n' $RETIRED_TAGS
}

delete_deployment() {
    # delete_deployment <function_name> [scope] [version-tag]
    local scope="${2:-$DEPLOYMENT_SCOPE}"
    echo "--- Removing deployment: $1-${scope}"
    local versions
    if [ -n "$3" ]; then versions="$3"; else versions=$(known_versions "$1" | sort -u); fi
    for v in $versions; do
        curl -sS -X DELETE "${FUNCTION_REGISTRY_URL}/function/deployments/remove/$1-${scope}" \
            -H "Content-Type: application/json" -d "{\"function_id\": \"$1:${v}\"}" | jq -c || true
    done
}

# Named functions only when given arguments, so a single-function upload does not tear
# down deployments it has no business touching. The va-uc-* endpoints are always cleared,
# since they are rebuilt from the company configs every round.
STATIC_TARGETS="${*:-va-bidding-pqt va-bid-eval va-rfp-requirements va-usecase-endpoints}"
for name_only in $STATIC_TARGETS; do
    [ "$name_only" = "va-usecase-endpoints" ] && continue   # handled below, one per company
    relative_path="${name_only}/function.json"
    json_path="${SCRIPT_DIR}/${relative_path}"
    [ -f "$json_path" ] || { echo "Skipping missing $json_path"; continue; }
    name=$(jq -r '.function_name' "$json_path")
    version=$(jq -r '.function_version' "$json_path")
    tag=$(jq -r '.function_release_tag' "$json_path")
    if [ -z "$name" ] || [ "$name" == "null" ]; then
        echo "Error: could not parse function metadata from $json_path"
        continue
    fi
    # Both scopes: OpenArcade creates "<function>-orcade" for the pqt and the evaluator,
    # while the compliance agents create "<function>-va-live" for va-rfp-requirements.
    # Whichever does not exist answers harmlessly.
    delete_deployment "$name" "$ORCADE_SCOPE"
    delete_deployment "$name" "$DEPLOYMENT_SCOPE"
    delete_one "${name}:${version}-${tag}"
done

# Versions retired along the way. The registry keeps every version, and a stale one is
# not harmless: the executor resolves a function artifact by id and caches it, so an old
# id can keep serving code from several uploads ago.
for retired in "va-bid-eval:1.0-stable" "va-bid-eval:1.1-stable" "va-bid-eval:1.2-stable" "va-bidding-pqt:1.0-stable" "va-bidding-pqt:1.1-stable"; do
    base="${retired%%:*}"
    case " $STATIC_TARGETS " in
        *" $base "*) delete_deployment "$base" "$ORCADE_SCOPE"; delete_one "$retired" ;;
    esac
done

# Only when the endpoints are actually being replaced. Clearing them for an unrelated
# upload would delete ten live deployments and hand the next round ten cold starts --
# the endpoints are no longer re-created mid-round, so nothing would bring them back
# before the evaluator called them.
case " $STATIC_TARGETS " in
    *" va-usecase-endpoints "*) ;;
    *) echo "Leaving the va-uc-* endpoints alone (not in this upload)."
       echo "Delete process complete."; exit 0 ;;
esac

echo "=== Deleting per-company va-uc-* endpoints ==="
# The names come from build_endpoints.py rather than from a second pass over the configs
# here, so the thing that builds them and the thing that removes them cannot disagree.
PYTHON="$GIT_ROOT/venv/bin/python"
[ -x "$PYTHON" ] || PYTHON=python3
# Both the current version and every retired one. The registry keeps every version, and
# a stale one is not harmless: the policies system resolves a function's artifact once
# and keeps serving it, which is how "va-uc-*:1.0-stable" deployments went on reading the
# answer key out of their settings after the answers had moved into the code zip.
ENDPOINT_VERSIONS=$("$PYTHON" -c "import sys; sys.path.insert(0, '$SCRIPT_DIR/../nodes'); \
from common.endpoint_names import ENDPOINT_VERSION, ENDPOINT_RELEASE_TAG, RETIRED_VERSIONS; \
print(' '.join(['%s-%s' % (ENDPOINT_VERSION, ENDPOINT_RELEASE_TAG)] + list(RETIRED_VERSIONS)))")
for name in $("$PYTHON" "$SCRIPT_DIR/build_endpoints.py" --list); do
    delete_deployment "$name"
    for v in $ENDPOINT_VERSIONS; do
        delete_one "${name}:${v}"
    done
done

echo "Delete process complete."
