#!/bin/bash
set -e

# Uploads the three shared functions and every company's live endpoints.
#
# The endpoints used to be uploaded by the AI Compliance Agents themselves, mid-bid.
# That put a registry upload and a first-ever deployment creation inside the bidding
# window, and warmup.sh could not cover them because they did not exist until the round
# was already under way. build.sh now produces one package per company per use case and
# they go up here, with the rest.

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

if [ -z "$FUNCTION_UPLOAD_URL" ]; then
    echo "Error: FUNCTION_UPLOAD_URL is not set in .env"
    exit 1
fi

FUNCTIONS_UPLOAD="${FUNCTION_UPLOAD_URL}/functions/upload"
FUNCTIONS_DIR="$(cd "$(dirname "$0")" && pwd)"

# Named functions only, when asked. Uploading all three deletes the pqt and evaluator
# deployments, and that costs an OpenArcade restart -- pointless when only
# va-rfp-requirements changed, since OpenArcade never calls it.
#
#   ./upload.sh                       all three
#   ./upload.sh va-rfp-requirements   just that one, no OpenArcade restart needed
#   ./upload.sh va-usecase-endpoints  the ten per-company endpoints, nothing else
ALL_FUNCTIONS="va-bidding-pqt va-bid-eval va-rfp-requirements va-usecase-endpoints"
ENDPOINT_BUILD_DIR="${FUNCTIONS_DIR}/va-usecase-endpoint/build"
TARGETS="${*:-$ALL_FUNCTIONS}"
for name in $TARGETS; do
    case " $ALL_FUNCTIONS " in
        *" $name "*) ;;
        *) echo "Error: unknown function '$name'. Known: $ALL_FUNCTIONS" >&2; exit 1 ;;
    esac
done

TOUCHES_OPENARCADE=0
for name in $TARGETS; do
    [ "$name" = "va-bidding-pqt" ] || [ "$name" = "va-bid-eval" ] && TOUCHES_OPENARCADE=1
done

echo "=== Deleting existing functions ==="
bash "$FUNCTIONS_DIR/delete.sh" $TARGETS

# The registry answers HTTP 200 with {"error": "..."} when the upload itself failed --
# its own storage backend being unreachable, for instance. Reporting the URIs regardless
# would announce two functions that are not there, and the failure would only surface
# much later as "Function not found" in the middle of a bid round.
FAILED=0

# "va-usecase-endpoints" is ten zips, not one, and their names come from the company
# configs -- so the list is expanded here rather than hard-coded.
ZIPS=""
for name in $TARGETS; do
    if [ "$name" = "va-usecase-endpoints" ]; then
        found=$(ls "$ENDPOINT_BUILD_DIR"/*.zip 2>/dev/null || true)
        if [ -z "$found" ]; then
            echo "Error: no endpoint packages in ${ENDPOINT_BUILD_DIR}. Run build.sh first." >&2
            exit 1
        fi
        ZIPS="$ZIPS $found"
    else
        zip_path="${FUNCTIONS_DIR}/${name}/${name}.zip"
        if [ ! -f "$zip_path" ]; then
            echo "Error: ${zip_path} not found. Run build.sh first."
            exit 1
        fi
        ZIPS="$ZIPS $zip_path"
    fi
done

for zip_path in $ZIPS; do
    name=$(basename "$zip_path" .zip)
    echo ""
    echo "=== Uploading ${name} ==="
    response=$(curl -sS -w $'\n%{http_code}' -X POST "$FUNCTIONS_UPLOAD" \
        -F "file=@${zip_path};type=application/zip")
    code=$(printf '%s' "$response" | tail -n1)
    body=$(printf '%s' "$response" | sed '$d')
    printf '%s\n' "$body" | jq . 2>/dev/null || printf '%s\n' "$body"

    error=$(printf '%s' "$body" | jq -r '.error // empty' 2>/dev/null)
    if [ "$code" != "200" ] && [ "$code" != "201" ]; then
        echo "  ! ${name}: HTTP ${code:-000}" >&2
        FAILED=$((FAILED+1))
    elif [ -n "$error" ]; then
        echo "  ! ${name}: ${error}" >&2
        FAILED=$((FAILED+1))
    fi
done

if [ "$FAILED" -gt 0 ]; then
    echo "" >&2
    echo "ERROR: ${FAILED} function(s) did not upload." >&2
    echo "" >&2
    echo "A 'Connection refused' to another host and port in the message above is the" >&2
    echo "registry reaching its own upload storage, not this script reaching the registry." >&2
    echo "That backend has to be running before any function can be registered -- including" >&2
    echo "the va-uc-* endpoints each AI Compliance Agent publishes mid-round." >&2
    exit 1
fi

echo ""
echo "Upload complete."
echo "Function URIs:"
# Read from each manifest rather than assuming: the versions move whenever a
# function's code changes, because the policies system caches a function's artifact by
# id and a re-upload under the same id keeps serving the old one.
for zip_path in $ZIPS; do
    name=$(basename "$zip_path" .zip)
    manifest="${FUNCTIONS_DIR}/${name}/function.json"
    if [ -f "$manifest" ]; then
        echo "  $(jq -r '"\(.function_name):\(.function_version)-\(.function_release_tag)"' "$manifest")"
    else
        echo "  ${name}:1.1-stable   (per-company endpoint)"
    fi
done

# --------------------------------------------------------------------------
# OpenArcade must be restarted before the next round. This is not optional.
#
# Both of these functions are stateful, so OpenArcade calls them through a deployment
# named "<function>-orcade". Its AgentFunctions instance caches that deployment id in
# `_deployment_cache` and, once cached, calls it directly and never creates it again
# (bids_example/agents_functions/__init__.py, the stateful branch of `call`).
#
# delete.sh removed those deployments just now -- it has to, or the new upload would sit
# in the registry while the old pod kept serving every call. But the running OpenArcade
# still holds the id, so its next call goes to a deployment that no longer exists:
#
#   POST /function/call_function/va-bidding-pqt-orcade
#     -> 500 "'NoneType' object has no attribute 'function_executor_uri'"
#
# Every bid submission then fails and the round ends with no bids at all. Restarting
# OpenArcade drops the cache, so the first call of the next round creates the deployment
# from the code uploaded above.
# --------------------------------------------------------------------------
echo ""
echo "=========================================================="
echo "REQUIRED NEXT STEPS -- both, in this order, before any round"
echo "=========================================================="
if [ "$TOUCHES_OPENARCADE" = "1" ]; then
echo "  1. restart OpenArcade so it forgets the deployments just deleted:"
echo "       \$K8S_CMD rollout restart deploy/orcade -n orcade"
echo "       \$K8S_CMD rollout status  deploy/orcade -n orcade"
echo ""
else
echo "  1. no OpenArcade restart needed -- it does not call any function uploaded here."
echo ""
fi
echo "  2. warm the new deployments so the round does not pay for their start-up:"
echo "       bash $(dirname "$0")/warmup.sh"
echo ""
echo "Skipping (1): OpenArcade keeps calling the deployments delete.sh removed and every"
echo "bid submission returns 500 ('function_executor_uri' on NoneType)."
echo ""
echo "Skipping (2): the first caller of each function waits for a container start and a"
echo "pip install. That broke three things at once in bid job 9db948a0 -- pqt 500s, the"
echo "compliance agents falling back to their own requirement lists, and the evaluator"
echo "timing out against OpenArcade's 60-second budget."
