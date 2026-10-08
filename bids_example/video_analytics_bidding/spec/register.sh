#!/bin/bash
# Register the 30 agent specs (6 roles x 5 companies) with the AIOS subject API.
#
#   ./register.sh                              all 30
#   ./register.sh CamFaceSolution              one company's 6
#   ./register.sh CamFaceSolution bid_manager  one agent
#
# Idempotent: an agent already registered is updated rather than duplicated.

set -o pipefail

GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
[ -z "$GIT_ROOT" ] && GIT_ROOT=$(pwd)
if [ -f "$GIT_ROOT/.env" ]; then
    set -a; source "$GIT_ROOT/.env"; set +a
else
    echo "Error: .env file MUST be present at $GIT_ROOT" >&2; exit 1
fi
if [ -z "$API_BASE_URL" ]; then
    echo "Error: API_BASE_URL is not set in .env" >&2; exit 1
fi

# Every agent in this example runs an OpenAI model, and the key each spec carries is
# copied from OPENAI_API_KEY in .env at the moment of registration -- there is no other
# source, and a pod reads its spec only at start-up. So a bad key registered here costs a
# full redeploy to find, and surfaces as five declined bids rather than as an error:
# every Bid Manager's first model call fails and each company declines at qualification.
# Checking it now is one request; the check sends the key only to OpenAI, to which it
# belongs, and prints only the status code. SKIP_KEY_CHECK=1 skips it (e.g. offline).
if [ -z "$OPENAI_API_KEY" ] || [[ "$OPENAI_API_KEY" == "<"* ]]; then
    echo "Error: OPENAI_API_KEY is not set in .env; every agent's model is openai:gpt-5.4-mini" >&2
    exit 1
fi
if [ "${SKIP_KEY_CHECK:-0}" != "1" ]; then
    KEY_STATUS=$(curl -s --max-time 15 -o /dev/null -w '%{http_code}' \
        https://api.openai.com/v1/models -H "Authorization: Bearer $OPENAI_API_KEY" || true)
    if [ "$KEY_STATUS" = "401" ]; then
        echo "Error: OpenAI rejects the OPENAI_API_KEY in .env (HTTP 401)." >&2
        echo "       Fix it before registering, or every company will decline at qualification." >&2
        echo "       (SKIP_KEY_CHECK=1 to register anyway.)" >&2
        exit 1
    elif [ "$KEY_STATUS" != "200" ]; then
        echo "Warning: could not confirm OPENAI_API_KEY with OpenAI (HTTP ${KEY_STATUS:-none}); continuing." >&2
    fi
fi

CUR_DIR=$(dirname "$(realpath "$0")")
COMPANIES=(CamFaceSolution MultiFaceTech NewGenTech UltraVideoTech VideoProcTech)
ROLES=(bid_manager ai_compliance sizing finance bid_reviewer head)

TARGET_COMPANY="$1"
TARGET_ROLE="$2"
REGISTERED=0; UPDATED=0; FAILED=0

register_one() {
    local company="$1" role="$2"
    local spec_file="$CUR_DIR/${company}/${role}.json"
    if [ ! -f "$spec_file" ]; then
        echo "  ! spec not found: $spec_file" >&2; FAILED=$((FAILED+1)); return 1
    fi

    local subject_id
    subject_id=$(jq -r '.identity.subject_id' "$spec_file")

    local eval_file="$CUR_DIR/${company}/${role}_evaluated.json"
    envsubst < "$spec_file" > "$eval_file"

    # Idempotence: if the subject already exists, PUT over it rather than POSTing a
    # duplicate. A second registration run must leave the registry exactly as the first.
    local existing
    existing=$(curl -s -o /dev/null -w "%{http_code}" "${API_BASE_URL}/api/subjects/${subject_id}")
    if [ "$existing" = "200" ]; then
        curl -s -X PUT -H "Content-Type: application/json" -d @"$eval_file" \
            "${API_BASE_URL}/api/subjects/${subject_id}" > /dev/null
        echo "  ~ updated  ${subject_id}"; UPDATED=$((UPDATED+1))
    else
        curl -s -X POST -H "Content-Type: application/json" -d @"$eval_file" \
            "${API_BASE_URL}/api/subjects" > /dev/null
        echo "  + created  ${subject_id}"; REGISTERED=$((REGISTERED+1))
    fi
    rm -f "$eval_file"
}

echo "=========================================================="
echo "Registering video analytics bidding agent specs"
echo "=========================================================="

for company in "${COMPANIES[@]}"; do
    [ -n "$TARGET_COMPANY" ] && [ "$company" != "$TARGET_COMPANY" ] && continue
    echo ""; echo "${company}:"
    for role in "${ROLES[@]}"; do
        [ -n "$TARGET_ROLE" ] && [ "$role" != "$TARGET_ROLE" ] && continue
        register_one "$company" "$role"
    done
done

echo ""
echo "created=${REGISTERED}  updated=${UPDATED}  failed=${FAILED}"
[ "$FAILED" -gt 0 ] && exit 1
exit 0
