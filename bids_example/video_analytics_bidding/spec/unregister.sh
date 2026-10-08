#!/bin/bash
# Remove everything register.sh and register_subjects_in_Exchange.sh created:
# the 30 agent specs and the 5 exchange subjects.
#
# Idempotent: a second run on an already-clean environment succeeds.

set -o pipefail

GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
[ -z "$GIT_ROOT" ] && GIT_ROOT=$(pwd)
if [ -f "$GIT_ROOT/.env" ]; then
    set -a; source "$GIT_ROOT/.env"; set +a
else
    echo "Error: .env file MUST be present at $GIT_ROOT" >&2; exit 1
fi

CUR_DIR=$(dirname "$(realpath "$0")")
COMPANIES=(CamFaceSolution MultiFaceTech NewGenTech UltraVideoTech VideoProcTech)
ROLES=(bid_manager ai_compliance sizing finance bid_reviewer head)

echo "=== Removing exchange subjects ==="
for company in "${COMPANIES[@]}"; do
    spec_file="$CUR_DIR/${company}/bid_manager.json"
    [ -f "$spec_file" ] || continue
    subject_id=$(jq -r '.identity.subject_id' "$spec_file")
    code=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE "${EXCHANGE_BASE_URL}/subjects/${subject_id}")
    case "$code" in
        200) echo "  - removed  ${subject_id}" ;;
        404) echo "  . absent   ${subject_id}" ;;
        *)   echo "  ! HTTP ${code} removing ${subject_id}" >&2 ;;
    esac
done

echo ""
echo "=== Removing agent specs ==="
for company in "${COMPANIES[@]}"; do
    for role in "${ROLES[@]}"; do
        spec_file="$CUR_DIR/${company}/${role}.json"
        [ -f "$spec_file" ] || continue
        subject_id=$(jq -r '.identity.subject_id' "$spec_file")
        code=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE "${API_BASE_URL}/api/subjects/${subject_id}")
        case "$code" in
            200|204) echo "  - removed  ${subject_id}" ;;
            404)     echo "  . absent   ${subject_id}" ;;
            *)       echo "  ! HTTP ${code} removing ${subject_id}" >&2 ;;
        esac
    done
done

echo ""
echo "Teardown complete."
