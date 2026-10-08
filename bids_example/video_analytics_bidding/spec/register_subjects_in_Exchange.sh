#!/bin/bash
# Register the five Bid Managers as ExchangeSubjects.
#
# Only Bid Managers become subjects. The 25 subordinate agents are internal to their
# companies and never receive a task from the exchange.
#
# The topic tagging is the point of the whole example. Two companies are never named in
# the buyer's task -- they reach the bid job solely because their subject carries the
# topic `videoanalytics_bidding`. Which companies those are comes from each
# `config.yaml`, not from this script, so re-tagging is a config edit.
#
# `task_evaluation_function` is deliberately omitted: it is consulted only by the
# exchange's `open` assignment mode, and this example uses `bidding`.
#
# Idempotent: a subject that already exists is updated in place.

set -o pipefail

TOPIC="videoanalytics_bidding"
EXPECTED_LISTENERS=2

GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
[ -z "$GIT_ROOT" ] && GIT_ROOT=$(pwd)
if [ -f "$GIT_ROOT/.env" ]; then
    set -a; source "$GIT_ROOT/.env"; set +a
else
    echo "Error: .env file MUST be present at $GIT_ROOT" >&2; exit 1
fi
if [ -z "$EXCHANGE_BASE_URL" ]; then
    echo "Error: EXCHANGE_BASE_URL is not set in .env" >&2; exit 1
fi

CUR_DIR=$(dirname "$(realpath "$0")")
NODES_DIR="$(realpath "$CUR_DIR/../nodes")"
PYTHON="$GIT_ROOT/venv/bin/python"
COMPANIES=(CamFaceSolution MultiFaceTech NewGenTech UltraVideoTech VideoProcTech)

CREATED=0; UPDATED=0; FAILED=0

echo "=========================================================="
echo "Registering Bid Managers as ExchangeSubjects"
echo "Exchange: $EXCHANGE_BASE_URL"
echo "=========================================================="

for company in "${COMPANIES[@]}"; do
    config="$NODES_DIR/${company}/config.yaml"
    if [ ! -f "$config" ]; then
        echo "  ! no config.yaml for ${company}" >&2; FAILED=$((FAILED+1)); continue
    fi

    # Build the subject payload from the company's own config, so the capability summary
    # and the topic list can never drift from what its agents actually read.
    payload=$("$PYTHON" - "$config" "$company" <<'PYEOF'
import json, sys, yaml

config_path, company = sys.argv[1], sys.argv[2]
with open(config_path) as fh:
    cfg = yaml.safe_load(fh)

company_block = cfg["company"]
credentials = cfg.get("credentials", {})
licensing = cfg.get("licensing", {})

payload = {
    "subject_id": company_block["subject_id"],
    "subject_metadata": {
        "owner": company_block["name"],
        "company": company_block["name"],
        "company_slug": company_block["slug"],
        "role": "bid_manager",
        "description": company_block.get("description", ""),
    },
    "subject_capabilities": {
        "usecases": [uc["id"] for uc in cfg.get("usecases", [])],
        "min_licenses": licensing.get("min_licenses"),
        "max_licenses": licensing.get("max_licenses"),
        "certifications": credentials.get("certifications", []),
        "projects_served": credentials.get("projects_served"),
        "licenses_supplied": credentials.get("licenses_supplied"),
    },
}
topics = company_block.get("topics") or []
if topics:
    payload["topics"] = topics

print(json.dumps(payload))
PYEOF
)
    if [ -z "$payload" ]; then
        echo "  ! could not build a payload for ${company}" >&2; FAILED=$((FAILED+1)); continue
    fi

    subject_id=$(echo "$payload" | jq -r '.subject_id')
    topics=$(echo "$payload" | jq -rc '.topics // []')

    existing=$(curl -s --max-time 15 -o /dev/null -w "%{http_code}" \
        "${EXCHANGE_BASE_URL}/subjects/${subject_id}")

    # The write's status code decides what we report. Discarding it and printing
    # "created" regardless would announce five registrations that never happened --
    # which is exactly what a wrong EXCHANGE_BASE_URL looks like.
    if [ "$existing" = "200" ]; then
        result=$(curl -s --max-time 15 -w $'\n%{http_code}' -X PATCH \
            -H "Content-Type: application/json" -d "$payload" \
            "${EXCHANGE_BASE_URL}/subjects/${subject_id}")
        verb="updated"
    else
        result=$(curl -s --max-time 15 -w $'\n%{http_code}' -X POST \
            -H "Content-Type: application/json" -d "$payload" \
            "${EXCHANGE_BASE_URL}/subjects")
        verb="created"
    fi
    code=$(printf '%s' "$result" | tail -n1)
    body=$(printf '%s' "$result" | sed '$d')

    case "$code" in
        200|201)
            if [ "$verb" = "updated" ]; then
                echo "  ~ updated  ${subject_id}  topics=${topics}"; UPDATED=$((UPDATED+1))
            else
                echo "  + created  ${subject_id}  topics=${topics}"; CREATED=$((CREATED+1))
            fi ;;
        000)
            echo "  ! ${subject_id}: no response from ${EXCHANGE_BASE_URL}" >&2
            FAILED=$((FAILED+1)) ;;
        *)
            echo "  ! ${subject_id}: HTTP ${code} on ${verb}" >&2
            [ -n "$body" ] && echo "      ${body:0:300}" >&2
            FAILED=$((FAILED+1)) ;;
    esac
done

echo ""
echo "created=${CREATED}  updated=${UPDATED}  failed=${FAILED}"

if [ "$FAILED" -gt 0 ]; then
    echo "" >&2
    echo "ERROR: ${FAILED} subject(s) did not register, so the checks below would only" >&2
    echo "report knock-on failures." >&2
    echo "" >&2
    echo "Check EXCHANGE_BASE_URL points at Xchange (exchange-db) and not at the job" >&2
    echo "exchange gateway -- they are different services on different ports, and the" >&2
    echo "gateway also answers on /subjects. See .env.template." >&2
    echo "" >&2
    echo "  bash ${CUR_DIR}/diagnose_exchange.sh" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Verify the tagging.
#
# Two separate things can go wrong and they need different fixes, so they are reported
# separately rather than collapsed into one count:
#
#   1. the exchange did not store `topics` at all -- the deployment predates the field
#   2. it stored them, but the topic query returns nothing -- the query path is the problem
#
# Either way the round would still complete, quietly, with only the invited companies,
# and the feature this example exists to show would go undemonstrated with nothing in
# the output to say so.
# ---------------------------------------------------------------------------
echo ""
echo "=== Verifying topic tagging ==="

# (1) Did `topics` survive the write? Read each tagged subject back rather than
# trusting the payload we sent -- an exchange that does not implement the field will
# accept it and silently discard it.
#
# A subject that cannot be read at all is a different problem from one that came back
# without topics, so the two are counted separately. Blaming the schema for what might
# be a 404 would send someone to fix the wrong thing.
PERSISTED=0
NO_TOPICS=()
UNREADABLE=()
for company in "${COMPANIES[@]}"; do
    config="$NODES_DIR/${company}/config.yaml"
    [ -f "$config" ] || continue
    subject_id=$("$PYTHON" -c "import sys,yaml;print(yaml.safe_load(open(sys.argv[1]))['company']['subject_id'])" "$config")
    wanted=$("$PYTHON" -c "import sys,yaml;print(len(yaml.safe_load(open(sys.argv[1]))['company'].get('topics') or []))" "$config")
    [ "$wanted" = "0" ] && continue

    response=$(curl -s --max-time 15 -w $'\n%{http_code}' "${EXCHANGE_BASE_URL}/subjects/${subject_id}")
    code=$(printf '%s' "$response" | tail -n1)
    body=$(printf '%s' "$response" | sed '$d')

    if [ "$code" != "200" ]; then
        echo "  UNREADABLE  ${subject_id}  HTTP ${code:-000}" >&2
        UNREADABLE+=("$subject_id")
        continue
    fi

    stored=$(printf '%s' "$body" | jq -rc '.data.topics // empty' 2>/dev/null)
    if [ -n "$stored" ] && [ "$stored" != "[]" ] && [ "$stored" != "null" ]; then
        echo "  stored      ${subject_id}  topics=${stored}"
        PERSISTED=$((PERSISTED+1))
    else
        echo "  NO TOPICS   ${subject_id}  read back without a topics field" >&2
        NO_TOPICS+=("$subject_id")
    fi
done

if [ "${#UNREADABLE[@]}" -gt 0 ]; then
    echo "" >&2
    echo "ERROR: ${#UNREADABLE[@]} subject(s) could not be read back from the exchange." >&2
    echo "They may not have registered, or this exchange serves subjects on a different" >&2
    echo "path. This is not a topics problem -- fix the registration first." >&2
    echo "" >&2
    echo "Run the diagnostics to see the raw responses:" >&2
    echo "  bash ${CUR_DIR}/diagnose_exchange.sh" >&2
    exit 1
fi

if [ "${#NO_TOPICS[@]}" -gt 0 ]; then
    echo "" >&2
    echo "ERROR: ${#NO_TOPICS[@]} subject(s) registered, but came back without their topics." >&2
    echo "The exchange accepted the field on write and did not return it on read. Until" >&2
    echo "the topics are stored, the two listener companies cannot join a bid job and" >&2
    echo "topic-based participation will not be demonstrated." >&2
    echo "" >&2
    echo "Confirm which it is -- the field being unsupported, or something else -- with:" >&2
    echo "  bash ${CUR_DIR}/diagnose_exchange.sh" >&2
    echo "" >&2
    echo "The other three companies are registered and a round will still run with them." >&2
    exit 1
fi

# (2) Does the topic query -- the one bidding mode itself runs to resolve a topic --
# return them? An empty body here is a different failure from an empty result set, so
# the HTTP status is captured rather than inferred from the payload.
response=$(curl -s --max-time 15 -w $'\n%{http_code}' -X POST "${EXCHANGE_BASE_URL}/subjects/query" \
    -H "Content-Type: application/json" \
    -d "{\"topics\": {\"\$in\": [\"${TOPIC}\"]}}")
http_code=$(printf '%s' "$response" | tail -n1)
body=$(printf '%s' "$response" | sed '$d')

if [ "$http_code" != "200" ]; then
    echo "" >&2
    echo "ERROR: POST ${EXCHANGE_BASE_URL}/subjects/query returned HTTP ${http_code:-000}." >&2
    [ -n "$body" ] && echo "Response: $body" >&2
    echo "" >&2
    echo "The topics are stored (${PERSISTED} subject(s) verified above), but the query" >&2
    echo "bidding mode uses to resolve them is not answering. Check the exchange is" >&2
    echo "reachable and that POST /subjects/query is supported by this deployment." >&2
    exit 1
fi

# jq prints nothing for empty input and still exits 0, so an unset count must be
# defaulted explicitly -- otherwise a transport failure reads as "found ".
count=$(printf '%s' "$body" | jq '(.data // []) | length' 2>/dev/null)
[ -z "$count" ] && count=0

echo "Subjects listening on '${TOPIC}': ${count}"
printf '%s' "$body" | jq -r '(.data // [])[] | "  - \(.subject_id)"' 2>/dev/null

if [ "$count" -ne "$EXPECTED_LISTENERS" ]; then
    echo "" >&2
    echo "ERROR: expected exactly ${EXPECTED_LISTENERS} topic listeners, found ${count}." >&2
    echo "Response body: $body" >&2
    echo "" >&2
    echo "The topics ARE stored on the subjects, so this is the query path, not the" >&2
    echo "tagging. If this exchange does not support querying by topics, bidding mode" >&2
    echo "cannot resolve them either and topic-based participation will not work." >&2
    exit 1
fi

if [ "$FAILED" -gt 0 ]; then
    exit 1
fi

echo ""
echo "Exchange subject registration complete."
