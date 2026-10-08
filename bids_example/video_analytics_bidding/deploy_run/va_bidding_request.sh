#!/bin/bash
set -e

# ==========================================================================
# Post one Video Analytics RFP to the Exchange and watch it through to a winner.
#
# This is the whole buyer-facing surface of the example: one task, one mode, no direct
# contact with the bidding system. XChange opens the bid job, OpenArcade runs it, and
# the winner comes back on the task.
#
#   RFP=chennai ./va_bidding_request.sh    use the alternative RFP
#   RESULT_TIMEOUT=3600 ./va_bidding_request.sh    wait longer for a slow round
#   DEBUG=true ./va_bidding_request.sh     trace commands (never traces .env)
#
# ONE MANUAL STEP IN MINIO, once per cluster. Set these three buckets to anonymous
# download (read-only) access:
#
#     va-bidding-rfp     the tender this task points at
#     va-bidding-eval    the image set the evaluator benchmarks against
#     va-bidding-docs    the commercial and sizing workbooks on each bid
#
#     MinIO Console -> Buckets -> <bucket> -> Anonymous -> Add Access Rule
#     Prefix: /     Access: readonly
#
# Nothing here inlines a document -- the task carries a URL and every reader fetches it
# for itself, which is what keeps the RFP input data rather than embedded knowledge.
# Those readers hold no MinIO credentials, so without the policy the round still runs
# and every link on it returns 403.
# ==========================================================================

GREEN='\033[0;32m'; RED='\033[0;31m'; CYAN='\033[0;36m'; YELLOW='\033[1;33m'; NC='\033[0m'

RFP=${RFP:-patna}
RESULT_TIMEOUT=${RESULT_TIMEOUT:-1800}
POLL_INTERVAL=${POLL_INTERVAL:-5}
DEBUG=${DEBUG:-false}

is_true() {
    case "$(echo "${1:-}" | tr '[:upper:]' '[:lower:]')" in
        true|1|yes|y|on) return 0 ;; *) return 1 ;;
    esac
}
is_true "$DEBUG" && set -x || true

SCRIPT_DIR=$(dirname "$(realpath "$0")")
GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo "$SCRIPT_DIR/../../..")

if [ -f "$GIT_ROOT/.env" ]; then
    echo -e "${CYAN}Loading .env from $GIT_ROOT${NC}"
    { set +x; } 2>/dev/null          # .env holds API keys and MinIO credentials
    set -a; source "$GIT_ROOT/.env"; set +a
    is_true "$DEBUG" && set -x || true
else
    echo -e "${RED}Error: .env not found at $GIT_ROOT${NC}" >&2
    exit 1
fi

EXCHANGE_URL=${EXCHANGE_BASE_URL:-"http://localhost:5000"}
BIDDING_URL=${OPENARCADE_BIDDING_URL:-"http://localhost:5000"}
PYTHON="$GIT_ROOT/venv/bin/python"

INVITED='["camfacesolution-bid-manager","multifacetech-bid-manager","newgentech-bid-manager"]'
TOPIC="videoanalytics_bidding"

echo -e "${CYAN}Exchange: $EXCHANGE_URL${NC}"
echo -e "${CYAN}Bidding:  $BIDDING_URL${NC}"

# --------------------------------------------------------------------------
# 1. Seed the RFP and the evaluation image set into MinIO.
# --------------------------------------------------------------------------
echo -e "\n${YELLOW}=== Seeding RFP and evaluation images ===${NC}"
RFP_JSON=$(RFP="$RFP" "$PYTHON" "$SCRIPT_DIR/seed_rfp.py") || {
    echo -e "${RED}Failed to upload the RFP to MinIO.${NC}" >&2; exit 1; }
EVAL_JSON=$("$PYTHON" "$SCRIPT_DIR/seed_eval_images.py") || {
    echo -e "${RED}Failed to upload the evaluation images to MinIO.${NC}" >&2; exit 1; }

RFP_URL=$(echo "$RFP_JSON" | jq -r '.url')
RFP_NAME=$(echo "$RFP_JSON" | jq -r '.rfp_name')
echo -e "${GREEN}RFP: $RFP_NAME${NC}"
echo -e "${GREEN}     $RFP_URL${NC}"
echo -e "${GREEN}Sample images: $(echo "$EVAL_JSON" | jq '.sample_images | length')${NC}"

# --------------------------------------------------------------------------
# 2. Build the task.
#
# rfp_url appears twice on purpose. In bidding mode task_data never reaches the
# subjects -- only bid_job_description is forwarded through OpenArcade into each
# bid_request -- so a Bid Manager reading only its bid request would otherwise never
# see the RFP at all.
#
# bid_job_mode "mixed": the buyer names three companies in bid_job_subject_ids AND
# asks for a topic, and the exchange resolves the UNION into the job's roster -- five
# bidders, none of which the buyer had to name. (closed takes only a list; open takes
# neither, and companies apply to it.) A mixed job's roster is fixed at creation, and
# OpenArcade tags it with `subject::<id>` for every subject on it, plus bid_job_tags.
#
# bid_job_tags carries the topic so that a company LISTENING on it -- UltraVideoTech and
# VideoProcTech poll OpenArcade for it -- can find the job by tag as well as by the
# bid_request. Either route may reach it first; the company bids once.
#
# Step 4 prints the resolved bidder count and the mode the job actually has.
# --------------------------------------------------------------------------
PAYLOAD=$(jq -n \
  --argjson rfp "$RFP_JSON" \
  --argjson evaluation "$EVAL_JSON" \
  --argjson invited "$INVITED" \
  --arg topic "$TOPIC" \
  --arg rfp_url "$RFP_URL" \
  --arg rfp_name "$RFP_NAME" \
  --arg registry "${FUNCTION_REGISTRY_URL:-}" \
  '{
    task_assignment_type: "bidding",
    task_data: {
      rfp: {bucket: $rfp.bucket, object: $rfp.object, url: $rfp.url},
      rfp_name: $rfp_name,
      project_type: "video_analytics",
      submitted_by: "procurement-user"
    },
    task_metadata: {
      task_assignment: {
        bid_job_name: {en: $rfp_name},
        bid_job_creator_id: "procurement-user",
        bid_job_evaluator_id: "va-bid-eval:1.3-stable",
        bid_job_pqt_id: "va-bidding-pqt:1.2-stable",
        bid_job_mode: "mixed",
        bid_job_subject_ids: $invited,
        topics: [$topic],
        bid_job_tags: [$topic],
        bid_job_description: {
          task_type: "video_analytics_rfp",
          rfp_url: $rfp_url,
          rfp_name: $rfp_name,
          text: ("Video Analytics RFP: " + $rfp_name + ". The full requirement document is at " + $rfp_url + " -- download and read it.")
        },
        bid_job_metadata: {
          priority: "high",
          evaluation: {
            sample_images: $evaluation.sample_images,
            weights: {cpu: 0.2, ram: 0.2, disk: 0.1, gpu: 0.5},
            # The evaluator calls the live va-uc-* endpoints through the registry, and
            # it cannot find the registry any other way: it runs as a stateful
            # deployment, and create_deployment does not carry function settings into
            # the pod. Without this the endpoint dimension silently scores 0 for all.
            functions_registry_url: $registry
          }
        }
      }
    }
  }')

echo -e "\n${CYAN}Request payload (evaluation images elided):${NC}"
echo "$PAYLOAD" | jq '.task_metadata.task_assignment.bid_job_metadata.evaluation.sample_images |= "<\(length) images + ground truth>"'

# --------------------------------------------------------------------------
# 3. Submit.
# --------------------------------------------------------------------------
echo -e "\n${YELLOW}=== POST /tasks ===${NC}"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$EXCHANGE_URL/tasks" \
    -H "Content-Type: application/json" -d "$PAYLOAD")
HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | head -n -1)

case "$HTTP_CODE" in
    200|201) ;;
    400)
        echo -e "${RED}400 -- the exchange rejected the task.${NC}" >&2
        echo "$BODY" | jq . >&2 || echo "$BODY" >&2
        echo -e "${YELLOW}The task is persisted as failed; nothing was sent to any subject." >&2
        echo -e "Check that task_assignment_type and task_data are present and that the" >&2
        echo -e "evaluator/pqt function ids exist in the registry.${NC}" >&2
        exit 1 ;;
    500)
        echo -e "${RED}500 -- the exchange could not persist the task.${NC}" >&2
        echo "$BODY" | jq . >&2 || echo "$BODY" >&2
        exit 1 ;;
    *)
        echo -e "${RED}Unexpected HTTP $HTTP_CODE from POST /tasks${NC}" >&2
        echo "$BODY" >&2; exit 1 ;;
esac

TASK_ID=$(echo "$BODY" | jq -r '.data.task_id // .task_id // empty')
if [ -z "$TASK_ID" ]; then
    echo -e "${RED}No task_id in the response:${NC}" >&2; echo "$BODY" >&2; exit 1
fi
echo -e "${GREEN}Task created: $TASK_ID${NC}"

# --------------------------------------------------------------------------
# 4. Read the task back. The inline POST response is a snapshot from before the
#    background thread ran, so the bid job only shows up on a fresh GET.
# --------------------------------------------------------------------------
sleep 2
echo -e "\n${YELLOW}=== GET /tasks/$TASK_ID ===${NC}"
TASK=$(curl -s "$EXCHANGE_URL/tasks/$TASK_ID")
echo "$TASK" | jq .

BID_JOB_ID=$(echo "$TASK" | jq -r '.data.task_metadata.bid_job_id // empty')
if [ -n "$BID_JOB_ID" ]; then
    echo -e "\n${CYAN}Bid job: $BID_JOB_ID${NC}"
    JOB_JSON=$(curl -s --max-time 15 "$BIDDING_URL/bid-jobs/$BID_JOB_ID" || true)
    RESOLVED=$(printf '%s' "$JOB_JSON" | jq -rc '.data.bid_job_subject_ids // [] | @json' 2>/dev/null)
    # An OpenArcade that predates bid_job_mode reports no mode at all, and runs the job
    # as closed. Saying so beats a blank that looks like a parsing mistake.
    JOB_MODE=$(printf '%s' "$JOB_JSON" | jq -r '.data.bid_job_mode // "not reported (server predates bid_job_mode; runs as closed)"' 2>/dev/null)
    JOB_TAGS=$(printf '%s' "$JOB_JSON" | jq -rc '.data.bid_job_tags // []' 2>/dev/null)
    echo -e "${CYAN}Mode: ${JOB_MODE:-unknown}   Tags: ${JOB_TAGS:-[]}${NC}"
    [ -z "$RESOLVED" ] && RESOLVED="[]"
    COUNT=$(printf '%s' "$RESOLVED" | jq 'length' 2>/dev/null)
    # jq prints nothing for empty input and still exits 0, so this must be defaulted
    # explicitly or the comparison below dies with "integer expression expected".
    [ -z "$COUNT" ] && COUNT=0
    echo -e "${CYAN}Resolved bidders ($COUNT): $RESOLVED${NC}"
    if [ "$COUNT" -eq 0 ]; then
        echo -e "${YELLOW}Could not read the bid job from $BIDDING_URL. The round may still${NC}"
        echo -e "${YELLOW}be running; polling continues below.${NC}"
    elif [ "$COUNT" -lt 5 ]; then
        echo -e "${YELLOW}Expected 5 bidders -- 3 invited by id plus 2 by topic '$TOPIC'.${NC}"
        echo -e "${YELLOW}Only $COUNT resolved, so the exchange did not combine the explicit list with${NC}"
        echo -e "${YELLOW}the topic. Check that the deployed Xchange supports bid_job_mode \"mixed\" and${NC}"
        echo -e "${YELLOW}that register_subjects_in_Exchange.sh has been run. The round will still${NC}"
        echo -e "${YELLOW}complete with the companies that were resolved.${NC}"
    else
        echo -e "${GREEN}Topic listeners joined: the round has all $COUNT bidders.${NC}"
    fi
else
    echo -e "${YELLOW}No bid_job_id yet -- the background thread may still be opening the job.${NC}"
fi

# --------------------------------------------------------------------------
# 5. Poll for the outcome.
#
# XChange has no server-side timeout: if one participant never bids, the task sits in
# "bidding" forever. The budget here is the only thing that ends the wait, so on expiry
# we say who is missing rather than just giving up.
# --------------------------------------------------------------------------
echo -e "\n${YELLOW}=== Polling GET /tasks/$TASK_ID/output every ${POLL_INTERVAL}s ===${NC}"
START=$(date +%s)
LAST_STATUS=""
{ set +x; } 2>/dev/null

while true; do
    OUT=$(curl -s "$EXCHANGE_URL/tasks/$TASK_ID/output" || true)
    STATUS=$(printf '%s' "$OUT" | jq -r '.data.task_assignment_status // "unknown"' 2>/dev/null)
    [ -z "$STATUS" ] && STATUS="unreachable"
    ELAPSED=$(( $(date +%s) - START ))

    if [ "$STATUS" != "$LAST_STATUS" ]; then
        echo -e "${CYAN}[${ELAPSED}s] status=${STATUS}${NC}"
        echo "$OUT" | jq . 2>/dev/null || echo "$OUT"
        LAST_STATUS="$STATUS"
    else
        printf "\r${CYAN}[%ss] status=%s${NC}   " "$ELAPSED" "$STATUS"
    fi

    if [ "$STATUS" = "completed" ]; then
        echo ""
        echo -e "\n${GREEN}=== Task completed ===${NC}"
        echo "$OUT" | jq .
        WINNER=$(echo "$OUT" | jq -r '.data.task_output.company // empty')
        [ -n "$WINNER" ] && echo -e "\n${GREEN}Winner: $WINNER${NC}"
        echo "$OUT" | jq -e '.data.task_output.scores' >/dev/null 2>&1 && {
            echo -e "${GREEN}Scores:${NC}"; echo "$OUT" | jq '.data.task_output.scores'; }
        break
    fi

    if [ "$STATUS" = "failed" ] || [ "$STATUS" = "rejected" ]; then
        echo ""
        echo -e "\n${RED}=== Task ended as $STATUS ===${NC}"
        echo "$OUT" | jq .
        exit 1
    fi

    if [ "$ELAPSED" -ge "$RESULT_TIMEOUT" ]; then
        echo ""
        echo -e "\n${RED}Timed out after ${ELAPSED}s with status=${STATUS}.${NC}"
        if [ -n "$BID_JOB_ID" ]; then
            echo -e "${YELLOW}Evaluation fires only once EVERY bidder has a bid on file.${NC}"
            REQUIRED=$(curl -s "$BIDDING_URL/bid-jobs/$BID_JOB_ID" | jq -r '.data.bid_job_subject_ids // [] | .[]')
            BIDS=$(curl -s "$BIDDING_URL/bid-jobs/$BID_JOB_ID/bids")
            echo -e "\n${CYAN}Bids on record:${NC}"
            echo "$BIDS" | jq -r '(.data // []) | .[] | "  \(.bid_subject_id)  status=\(.bid_data.bid_status // "?")  rejected=\(.bid_data.bid_rejected // false)  budget=\(.bid_data.total_budget // "-")"'
            echo -e "\n${RED}Still waiting on:${NC}"
            for subject in $REQUIRED; do
                echo "$BIDS" | jq -e --arg s "$subject" '(.data // []) | map(select(.bid_subject_id == $s)) | length > 0' >/dev/null \
                    || echo -e "${RED}  $subject  (no bid submitted -- check this pod's logs)${NC}"
            done
        fi
        exit 1
    fi
    sleep "$POLL_INTERVAL"
done

echo -e "\n${GREEN}Round complete.${NC}"
