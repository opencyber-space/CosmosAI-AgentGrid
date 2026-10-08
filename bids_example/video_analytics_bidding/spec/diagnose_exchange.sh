#!/bin/bash
# What does this exchange actually support?
#
# `register_subjects_in_Exchange.sh` can tell that topic tagging is not working, but not
# why. There are several distinct causes and they need different fixes:
#
#   - the exchange does not implement ExchangeSubjects.topics at all
#   - it implements them but drops unknown fields on POST
#   - it stores them but /subjects/{id} answers in a shape we are not reading
#   - /subjects/query does not support the $in operator
#
# This prints the raw responses so the cause is visible rather than inferred. It writes
# one throwaway subject and deletes it again; it does not touch the five real ones.

TOPIC="videoanalytics_bidding"
PROBE_ID="va-diagnostic-probe"
# A second, distinct topic. PATCHing a subject with the topics it already has proves
# nothing -- an exchange that ignores the field entirely would still read back the
# original value and look like a success. Changing the value makes the read decisive.
PATCH_TOPIC="va-diagnostic-probe-topic"

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

EX="${EXCHANGE_BASE_URL%/}"
echo "=========================================================="
echo "Exchange diagnostics"
echo "Exchange: $EX"
echo "=========================================================="

show() {
    # show <label> <curl args...>
    local label="$1"; shift
    echo ""
    echo "--- ${label}"
    local out code body
    out=$(curl -s --max-time 15 -w $'\n%{http_code}' "$@" 2>&1)
    code=$(printf '%s' "$out" | tail -n1)
    body=$(printf '%s' "$out" | sed '$d')
    echo "HTTP ${code:-000}"
    if [ -n "$body" ]; then
        printf '%s\n' "$body" | jq . 2>/dev/null || printf '%s\n' "$body"
    else
        echo "(empty body)"
    fi
}

# 1. Is the exchange reachable, and does an existing subject read back at all?
show "GET /subjects/ultravideotech-bid-manager  (one of the five just registered)" \
    "$EX/subjects/ultravideotech-bid-manager"

# 2. Does a plain query work? This tells us whether /subjects/query exists before we
#    blame the $in operator for anything.
#
# Note both of these queries run against whatever is registered *now*. If the exchange
# is empty they come back empty, which says nothing about the query path -- that is what
# the probe below exists to settle.
show "POST /subjects/query  {}  (every subject)" \
    -X POST "$EX/subjects/query" -H "Content-Type: application/json" -d '{}'

# 3. Does the topic query work -- the exact filter bidding mode runs to resolve a topic?
show "POST /subjects/query  {\"topics\": {\"\$in\": [\"$TOPIC\"]}}" \
    -X POST "$EX/subjects/query" -H "Content-Type: application/json" \
    -d "{\"topics\": {\"\$in\": [\"$TOPIC\"]}}"

# 4. Write a throwaway subject WITH topics and read it straight back. This is the
#    decisive test: if topics come back, the field is supported and the earlier failure
#    is elsewhere; if they do not, the exchange is dropping them on write.
echo ""
echo "=========================================================="
echo "Probe: does a freshly written subject keep its topics?"
echo "=========================================================="
curl -s --max-time 15 -X DELETE "$EX/subjects/$PROBE_ID" > /dev/null 2>&1

show "POST /subjects  (probe, with topics)" \
    -X POST "$EX/subjects" -H "Content-Type: application/json" \
    -d "{\"subject_id\": \"$PROBE_ID\", \"subject_metadata\": {\"probe\": true}, \"subject_capabilities\": {}, \"topics\": [\"$TOPIC\"]}"

show "GET /subjects/$PROBE_ID  (read it back)" "$EX/subjects/$PROBE_ID"

# 5. Now that one subject definitely carries the topic, re-run the query bidding mode
#    uses. Running it before the probe existed -- as the baseline above does -- can only
#    ever return empty on an empty exchange, which proves nothing about the query path.
show "POST /subjects/query  {\"topics\": {\"\$in\": [\"$TOPIC\"]}}  (with the probe present)" \
    -X POST "$EX/subjects/query" -H "Content-Type: application/json" \
    -d "{\"topics\": {\"\$in\": [\"$TOPIC\"]}}"

# 6. Can topics be *changed* on an existing subject? PATCHing the value it already has
#    would read back identically even from an exchange that ignored the field, so this
#    patches to a different topic and looks for that one specifically.
show "PATCH /subjects/$PROBE_ID  (change topics to [\"$PATCH_TOPIC\"])" \
    -X PATCH "$EX/subjects/$PROBE_ID" -H "Content-Type: application/json" \
    -d "{\"topics\": [\"$PATCH_TOPIC\"]}"

show "GET /subjects/$PROBE_ID  (after PATCH -- expect topics=[\"$PATCH_TOPIC\"])" \
    "$EX/subjects/$PROBE_ID"

echo ""
echo "--- cleaning up the probe"
curl -s --max-time 15 -o /dev/null -w "DELETE /subjects/$PROBE_ID -> HTTP %{http_code}\n" \
    -X DELETE "$EX/subjects/$PROBE_ID"

echo ""
echo "=========================================================="
echo "How to read this"
echo "=========================================================="
cat <<'EOF'
  Read the PROBE results first. The baseline queries at the top run against whatever
  is registered at the time, so on an empty exchange they are empty for a reason that
  has nothing to do with topics.

  Probe POST succeeded, GET came back WITHOUT topics
      The exchange accepts the field and discards it -- it does not implement
      ExchangeSubjects.topics. Topic-based participation needs an exchange update.

  Probe GET came back WITH topics, but the query WITH THE PROBE PRESENT found nothing
      The field is stored; the query path is the problem. Bidding mode resolves a
      topic with exactly that $in filter, so it would not find them either.

  Probe GET came back WITH topics and the query found the probe
      Tagging and querying both work, and this exchange is not the problem.
      If the five real subjects still 404 or read back without topics, they simply
      are not registered here -- check EXCHANGE_BASE_URL points at Xchange
      (exchange-db) and not at the job exchange gateway, then re-run
      register_subjects_in_Exchange.sh.

  GET of a real subject returned 404 while the probe round-tripped fine
      The exchange is healthy and empty of our subjects: registration never reached
      it. Same fix as above -- the URL, then re-register.
EOF
