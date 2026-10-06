#!/bin/bash
set -e

# T001: Script created
# T003: Define ANSI color codes
GREEN='\033[0;32m'
RED='\033[0;31m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# ==========================================================
# WHICH JOBS TO RUN - edit these, then run the script.
# RUN_ALL=true runs every job; otherwise each ONLY_* flag decides on its own.
# Any of them can also be overridden for one run, e.g.  ONLY_IMAGE=true bash bids_inference_request.sh
# ==========================================================
RUN_ALL=${RUN_ALL:-false}
ONLY_SECURITY=${ONLY_SECURITY:-true}
ONLY_FRONTEND=${ONLY_FRONTEND:-false}
ONLY_IMAGE=${ONLY_IMAGE:-false}
ONLY_CONTENT=${ONLY_CONTENT:-false}

# DEBUG=true traces every command (bash -x). Off by default: it echoes each line of this
# script and every API response, and .env is never traced whatever this is set to.
DEBUG=${DEBUG:-false}

# true/false, yes/no and 1/0 are all accepted for the flags above.
is_true() {
    case "$(echo "${1:-}" | tr '[:upper:]' '[:lower:]')" in
        true|1|yes|y|on) return 0 ;;
        *) return 1 ;;
    esac
}

if is_true "$DEBUG"; then
    set -x
fi

if is_true "$RUN_ALL"; then
    ONLY_SECURITY=true
    ONLY_FRONTEND=true
    ONLY_IMAGE=true
    ONLY_CONTENT=true
fi

if ! is_true "$ONLY_SECURITY" && ! is_true "$ONLY_FRONTEND" && ! is_true "$ONLY_IMAGE" && ! is_true "$ONLY_CONTENT"; then
    echo "Nothing selected: set RUN_ALL=true or one of ONLY_SECURITY / ONLY_FRONTEND / ONLY_IMAGE / ONLY_CONTENT at the top of this script." >&2
    exit 1
fi

# T002: Load .env from git root
GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo ".")
if [ -f "$GIT_ROOT/.env" ]; then
    echo -e "${CYAN}Loading .env from $GIT_ROOT${NC}"
    # Never trace this: .env holds API keys and MinIO credentials.
    { set +x; } 2>/dev/null
    source "$GIT_ROOT/.env"
    is_true "$DEBUG" && set -x || true
else
    echo -e "${YELLOW}Warning: .env file not found at $GIT_ROOT${NC}"
fi

# Fallback default
API_URL=${OPENARCADE_BIDDING_URL:-"http://localhost:5000"}
echo -e "${CYAN}Using API URL: $API_URL${NC}"
echo -e "${CYAN}Jobs selected -> security=$ONLY_SECURITY frontend=$ONLY_FRONTEND image=$ONLY_IMAGE content=$ONLY_CONTENT (RUN_ALL=$RUN_ALL)${NC}"

# T004: Function to create a bid job
create_bid_job() {
    local payload="$1"
    echo -e "${CYAN}Creating Bid Job...${NC}" >&2
    
    local response
    response=$(curl -s -w "\n%{http_code}" -X POST "$API_URL/bid-jobs" \
        -H "Content-Type: application/json" \
        -d "$payload")
        
    local http_code
    http_code=$(echo "$response" | tail -n1)
    local body
    body=$(echo "$response" | tail -n +1 | head -n -1)

    if [ "$http_code" != "201" ] && [ "$http_code" != "200" ]; then
        echo -e "${RED}Failed to create bid job. HTTP Code: $http_code${NC}" >&2
        echo "$body" >&2
        return 1
    fi

    # Extract bid_job_id (assuming standard openarcade return shape or just ID directly)
    local job_id
    job_id=$(echo "$body" | jq -r '.data.bid_job_id // .bid_job_id // empty')
    
    if [ -z "$job_id" ]; then
        echo -e "${RED}Could not extract bid_job_id from response:${NC}" >&2
        echo "$body" >&2
        return 1
    fi
    
    echo -e "${GREEN}Created Bid Job ID: $job_id${NC}" >&2
    echo "$job_id"
}

# Print the bids on record as a short list instead of the raw JSON blob.
print_bids() {
    echo "$1" | jq -r '
        (.data // .)
        | if type == "array" then . else [] end
        | to_entries[]
        | "  \(.key + 1). \(.value.bid_subject_id)"
          + "\n       bid_status=\(.value.bid_data.bid_status // .value.bid_data.status // "?")"
          + "  tokens=\(.value.bid_data.total_estimated_tokens // "?")"
          + "  compute=\(.value.bid_data.required_compute // "?")"
          + "  timeline=\(.value.bid_data.proposed_timeline // "-")"
          + "\n       is_winner=\(.value.is_winner)  submitted=\(.value.submission_time)"
          + (if (.value.bid_data.reason // "") == "" then "" else "\n       reason: \(.value.bid_data.reason | .[0:200])" end)
    ' 2>/dev/null || echo "  (could not parse the bids response)"
}

# T005: Function to poll for bids
poll_bids() {
    local job_id="$1"
    local expected_count="$2"
    local timeout=120 # 60 seconds timeout
    local start_time=$(date +%s)
    local current_time
    local elapsed
    # `set -x` would echo the whole JSON response on every poll, so trace off here and
    # print the parsed bids instead; the caller's setting is restored on the way out.
    local had_xtrace=0
    case "$-" in *x*) had_xtrace=1; set +x ;; esac

    echo -e "${YELLOW}Polling for bids (waiting for $expected_count bids)...${NC}"

    local last_count=-1
    while true;
    do
        local response
        response=$(curl -s "$API_URL/bid-jobs/$job_id/bids" || true)  # tolerate transient network errors

        # We expect a JSON array or a data wrapper depending on openarcade version. 
        # Usually it's in .data or the root is an array.
        local count
        count=$(echo "$response" | jq 'if type == "array" then length elif .data then (.data | length) else 0 end' 2>/dev/null || echo 0)

        if [ "$count" != "$last_count" ]; then
            echo -e "${CYAN}Bids so far: $count/$expected_count${NC}"
            [ "$count" -gt 0 ] && print_bids "$response" || true
            last_count=$count
        fi

        if [ "$count" -ge "$expected_count" ]; then
            echo -e "${GREEN}Received $count bids!${NC}"
            [ "$had_xtrace" = "1" ] && set -x || true
            break
        fi

        current_time=$(date +%s)
        elapsed=$((current_time - start_time))
        if [ "$elapsed" -ge "$timeout" ]; then
            echo -e "${RED}Timeout reached while polling for bids ($elapsed seconds). Found $count/$expected_count.${NC}"
            [ "$had_xtrace" = "1" ] && set -x || true
            return 1
        fi

        sleep 2
    done
}

# T006: Poll task results until the evaluator has delivered the bid_winner task.
# Orcade evaluates only after EVERY subject has bid, and both the evaluator call
# and the winner notification run on background threads - so the winner does not
# exist at the moment the last bid lands. Polling here (rather than a single
# fetch) is what makes the winner observable.
fetch_task_results() {
    local job_id="$1"
    # Real image edits take minutes per stage; override with RESULT_TIMEOUT if needed.
    local timeout=${RESULT_TIMEOUT:-600}
    local start_time=$(date +%s)
    local elapsed
    # Same reason as poll_bids: the raw task-results JSON is far too big to trace.
    local had_xtrace=0
    case "$-" in *x*) had_xtrace=1; set +x ;; esac

    echo -e "${YELLOW}Waiting for evaluation and bid_winner delivery...${NC}"

    while true; do
        local response winner
        response=$(curl -s "$API_URL/bid-jobs/$job_id/task-results" || true)  # tolerate transient network errors
        # (.data // .) tolerates both wrapper shapes; the array guard avoids
        # "Cannot index array with string" when no task results exist yet.
        winner=$(echo "$response" \
            | jq -r '(.data // .) | if type == "array" then (.[] | select(.task_type == "bid_winner") | .bid_subject_id) else empty end' 2>/dev/null)

        if [ -n "$winner" ]; then
            echo -e "${GREEN}Winner: ${winner}${NC}"
            echo -e "${GREEN}Winner Result:${NC}"
            echo "$response" \
                | jq -r '(.data // .) | if type == "array" then (.[] | select(.task_type == "bid_winner") | {bid_subject_id, task_type, task_result, created_time}) else empty end'
            [ "$had_xtrace" = "1" ] && set -x || true
            return 0
        fi

        elapsed=$(( $(date +%s) - start_time ))
        if [ "$elapsed" -ge "$timeout" ]; then
            echo -e "${RED}Timeout after ${elapsed}s waiting for bid_winner.${NC}"
            echo -e "${YELLOW}Bids on record:${NC}"
            print_bids "$(curl -s "$API_URL/bid-jobs/$job_id/bids" || true)"
            [ "$had_xtrace" = "1" ] && set -x || true
            return 1
        fi
        sleep 3
    done
}


# ---------------------------------------------------------
# Phase 3: User Story 1 (Security Audit)
# ---------------------------------------------------------
echo -e "\n${YELLOW}=== Executing User Story 1: Security Audit Job ===${NC}"

# T007: Define US1 Payload
PAYLOAD_US1=$(cat << 'JSON'
{
  "bid_job_name": {
    "en": "Security Audit Pass"
  },
  "bid_job_description": {
    "task_type": "security_review",
    "text": "Review the authentication service for OWASP Top 10 vulnerabilities.\n\n=== FILE: auth_service.py ===\nimport hashlib, sqlite3, jwt\nSECRET = \"hardcoded-dev-secret\"\n\ndef login(username, password):\n    conn = sqlite3.connect(\"users.db\")\n    q = \"SELECT id, password_hash FROM users WHERE username = '\" + username + \"'\"\n    row = conn.execute(q).fetchone()\n    if not row:\n        return None\n    if hashlib.md5(password.encode()).hexdigest() == row[1]:\n        return jwt.encode({\"uid\": row[0]}, SECRET, algorithm=\"HS256\")\n    return None\n\ndef reset_password(user_id, new_password):\n    conn = sqlite3.connect(\"users.db\")\n    conn.execute(\"UPDATE users SET password_hash='%s' WHERE id=%s\"\n                 % (hashlib.md5(new_password.encode()).hexdigest(), user_id))\n    conn.commit()\n\n=== FILE: requirements.txt ===\nFlask==1.1.2\nPyJWT==1.7.1\nrequests==2.19.1\ncryptography==2.3\n\n=== FILE: auth_config.yaml ===\nsession:\n  cookie_secure: false\n  cookie_httponly: false\n  idle_timeout_minutes: 1440\npassword_policy:\n  min_length: 4\n  require_mfa: false\nrate_limiting:\n  enabled: false\nlogging:\n  log_request_body: true\n  redact_fields: []",
    "acceptance_criteria": {
      "forbidden_pins": [
        "Flask==1.1.2",
        "PyJWT==1.7.1",
        "requests==2.19.1",
        "cryptography==2.3"
      ],
      "required_config": {
        "session.cookie_secure": true,
        "session.cookie_httponly": true,
        "password_policy.require_mfa": true,
        "rate_limiting.enabled": true,
        "logging.log_request_body": false
      },
      "forbidden_code": [
        "hardcoded-dev-secret"
      ]
    }
  },
  "bid_job_metadata": {
    "priority": "high"
  },
  "bid_job_evaluator_id": "bids-evaluator:1.1-stable",
  "bid_job_pqt_id": "dummy-pqt:1.0-stable",
  "bid_job_creator_id": "user",
  "bid_job_subject_ids": [
    "manager1-security-audit",
    "manager2-frontend",
    "manager3-image-editing",
    "manager4-content-creation",
    "manager5-security-audit"
  ],
  "bid_job_mode": "closed",
  "bid_job_max_subjects": null,
  "bid_job_max_time": null
}
JSON
)

# T009: Print Request payload
echo -e "${CYAN}Request Payload:${NC}"
echo "$PAYLOAD_US1" | jq .

# T008: Execute job 1 flow
if ! is_true "$ONLY_SECURITY"; then
    echo -e "${YELLOW}ONLY_SECURITY is false - skipping the security audit job.${NC}"
elif JOB_ID_1=$(create_bid_job "$PAYLOAD_US1") && [ -n "$JOB_ID_1" ] && [ "$JOB_ID_1" != "1" ]; then
    # Evaluation is bid-driven: it fires only once EVERY eligible subject has
    # bid, so wait for one bid per subject_id rather than a hardcoded count.
    # Managers that decline still submit a declining bid, so this count is met.
    EXPECTED_US1=$(echo "$PAYLOAD_US1" | jq '.bid_job_subject_ids | length')
    if poll_bids "$JOB_ID_1" "$EXPECTED_US1"; then
        fetch_task_results "$JOB_ID_1" || echo -e "${RED}No winner was delivered for the security job.${NC}"
    fi
else
    echo -e "${RED}Skipping polling for US1 due to creation failure.${NC}"
fi

# Nothing left to do when only the security job was selected.
if ! is_true "$ONLY_FRONTEND" && ! is_true "$ONLY_IMAGE" && ! is_true "$ONLY_CONTENT"; then
    echo -e "\n${GREEN}All selected bid jobs processed successfully.${NC}"
    exit 0
fi
# ---------------------------------------------------------
# Phase 4: User Story 2 (Frontend, Image Editing, Content Creation)
# ---------------------------------------------------------
echo -e "\n${YELLOW}=== Executing User Story 2: Remaining Managers ===${NC}"

# T010: Define US2 Payloads
declare -A US2_PAYLOADS

US2_PAYLOADS["manager2-frontend"]=$(cat << 'JSON'
{
  "bid_job_name": {
    "en": "Frontend React Components"
  },
  "bid_job_description": {
    "task_type": "frontend_dev",
    "text": "Build a responsive login form component using React and TailwindCSS.\n\n=== FILE: src/components/LoginForm.jsx ===\nimport React, { useState } from \"react\";\n\nexport default function LoginForm({ onSubmit }) {\n  const [email, setEmail] = useState(\"\");\n  const [password, setPassword] = useState(\"\");\n  return (\n    <form onSubmit={(e) => { e.preventDefault(); onSubmit({ email, password }); }}>\n      <input value={email} onChange={(e) => setEmail(e.target.value)} />\n      <input type=\"password\" value={password} onChange={(e) => setPassword(e.target.value)} />\n      <button type=\"submit\">Sign in</button>\n    </form>\n  );\n}\n\n=== FILE: src/api/auth.js ===\nexport async function login(payload) {\n  const res = await fetch(\"/api/login\", { method: \"POST\", body: JSON.stringify(payload) });\n  return res.json();\n}\n\n=== REQUIREMENTS ===\n- Tailwind utility classes only, no separate CSS files\n- Responsive at 375px, 768px and 1280px\n- Inline validation errors plus a submit loading state\n- Keyboard accessible, labelled inputs, WCAG AA contrast\n\n=== FILE: src/api/endpoints.md ===\nPOST /api/login      -> { email, password }        => { token, refreshToken, user }\nPOST /api/logout     -> { token }                  => { ok }\nGET  /api/session    -> header: Authorization      => { user, expiresAt }\nPOST /api/refresh    -> { refreshToken }           => { token, expiresAt }\nnotes: token goes in an httpOnly cookie; refresh on 401 then retry once"
  },
  "bid_job_metadata": {
    "priority": "medium"
  },
  "bid_job_evaluator_id": "bids-evaluator:1.1-stable",
  "bid_job_pqt_id": "dummy-pqt:1.0-stable",
  "bid_job_creator_id": "user",
  "bid_job_subject_ids": [
    "manager1-security-audit",
    "manager2-frontend",
    "manager3-image-editing",
    "manager4-content-creation",
    "manager5-security-audit"
  ],
  "bid_job_mode": "closed",
  "bid_job_max_subjects": null,
  "bid_job_max_time": null
}
JSON
)

US2_PAYLOADS["manager3-image-editing"]=$(cat << 'JSON'
{
  "bid_job_name": {
    "en": "Hero Image Enhancement"
  },
  "bid_job_description": {
    "task_type": "image_processing",
    "text": "Upscale and color-correct the provided hero banner image. The image itself is stored in MinIO (bucket marketing-images, see input_image).\n\n=== FILE: assets/hero_banner.json (image descriptor) ===\n{\"filename\": \"hero_banner.png\", \"width\": 1280, \"height\": 720, \"dpi\": 72,\n \"color_space\": \"sRGB\", \"bit_depth\": 8, \"has_alpha\": true, \"avg_luminance\": 0.31,\n \"exif\": {\"Make\": \"Canon\", \"Model\": \"EOS 90D\", \"GPSLatitude\": \"12.9716N\",\n          \"GPSLongitude\": \"77.5946E\", \"Artist\": \"internal-photographer\"}}\n\n=== REQUIREMENTS ===\n- Target 2560x1440 at 144 DPI for retina hero placement\n- Correct the underexposure (avg luminance 0.31) without clipping highlights\n- Strip GPS and Artist EXIF before publication, keep the colour profile\n- Apply a visible watermark bottom-right at 12% opacity\n\n=== SCENE CONTENTS (for segmentation) ===\nforeground: two people seated at a laptop, left-of-centre\nmidground: wooden desk with a coffee cup, notebook and phone\nbackground: office window with blinds, potted plant far right\nnotes: soft backlight from the window; subject faces are partially shadowed",
    "acceptance_criteria": {
      "width": 2560,
      "height": 1440,
      "dpi": 144,
      "luminance_must_increase": true,
      "highlights_must_not_increase": true,
      "remove_exif_tags": [
        "GPSInfo",
        "Artist"
      ],
      "keep_icc_profile": true
    }
  },
  "bid_job_metadata": {
    "priority": "low"
  },
  "bid_job_evaluator_id": "bids-evaluator:1.1-stable",
  "bid_job_pqt_id": "dummy-pqt:1.0-stable",
  "bid_job_creator_id": "user",
  "bid_job_subject_ids": [
    "manager1-security-audit",
    "manager2-frontend",
    "manager3-image-editing",
    "manager4-content-creation",
    "manager5-security-audit"
  ],
  "bid_job_mode": "closed",
  "bid_job_max_subjects": null,
  "bid_job_max_time": null
}
JSON
)

US2_PAYLOADS["manager4-content-creation"]=$(cat << 'JSON'
{
  "bid_job_name": {
    "en": "Marketing Copy"
  },
  "bid_job_description": {
    "task_type": "content_generation",
    "text": "Write an SEO optimized blog post of about 300 words (270-330 words of prose) about the new AgentGrid features.\n\n=== FILE: drafts/agentgrid_release.md ===\n# AgentGrid new stuff\n\nWe shipped some new things this quarter. AgentGrid now has bidding, so agents can\nbid on jobs. there is also a evaluator that picks a winner. Its very useful for\nteams who wants to scale there agent workloads. We also added observability so you\ncan see what happend.\n\nBidding works by sending a job to managers and they respond. The winner does the\nwork with its subagents.\n\n=== TARGET KEYWORDS ===\nmulti-agent orchestration, agent bidding system, AI workflow automation, AgentGrid\n\n=== REQUIREMENTS ===\n- Article body: 270-330 WORDS of prose. Headings and the meta description do not count.\n- Keep the H1 exactly as given; add at least 2 H2 sections.\n- Meta description: at most 155 CHARACTERS (characters, not words). Return it in its own\n  field - do not write it inside the article.\n- Fix grammar and spelling (\"its\", \"there\", \"happend\", \"who wants\").\n- Use every target keyword naturally, 1-2% density each, no stuffing; include one internal CTA.",
    "acceptance_criteria": {
      "body_words_min": 270,
      "body_words_max": 330,
      "meta_description_max_chars": 155,
      "h1_count": 1,
      "h2_min": 2,
      "keywords": [
        "multi-agent orchestration",
        "agent bidding system",
        "AI workflow automation",
        "AgentGrid"
      ],
      "keyword_density_pct": [
        1,
        2
      ]
    }
  },
  "bid_job_metadata": {
    "priority": "high"
  },
  "bid_job_evaluator_id": "bids-evaluator:1.1-stable",
  "bid_job_pqt_id": "dummy-pqt:1.0-stable",
  "bid_job_creator_id": "user",
  "bid_job_subject_ids": [
    "manager1-security-audit",
    "manager2-frontend",
    "manager3-image-editing",
    "manager4-content-creation",
    "manager5-security-audit"
  ],
  "bid_job_mode": "closed",
  "bid_job_max_subjects": null,
  "bid_job_max_time": null
}
JSON
)

# Seed the hero banner into MinIO and attach it to the image job as input_image.
# seed_image.py prints the {bucket, object, url, facts} reference on stdout.
SCRIPT_DIR=$(dirname "$(realpath "$0")")
SKIP_IMAGE_JOB=0
if ! is_true "$ONLY_IMAGE"; then
    SKIP_IMAGE_JOB=1
elif SEED_JSON=$("$GIT_ROOT/venv/bin/python" "$SCRIPT_DIR/seed_image.py"); then
    US2_PAYLOADS["manager3-image-editing"]=$(echo "${US2_PAYLOADS[manager3-image-editing]}" \
        | jq --argjson img "$SEED_JSON" '.bid_job_description.input_image = $img')
else
    echo -e "${RED}Seeding the hero banner into MinIO failed - skipping the image-editing job.${NC}"
    SKIP_IMAGE_JOB=1
fi

# T011 & T012: Loop through each payload sequentially
for agent_id in "manager2-frontend" "manager3-image-editing" "manager4-content-creation"; do
    case "$agent_id" in
        manager2-frontend)        is_true "$ONLY_FRONTEND" || continue ;;
        manager3-image-editing)   is_true "$ONLY_IMAGE" || continue ;;
        manager4-content-creation) is_true "$ONLY_CONTENT" || continue ;;
    esac
    if [ "$agent_id" = "manager3-image-editing" ] && [ "$SKIP_IMAGE_JOB" = "1" ]; then
        continue
    fi
    echo -e "\n${CYAN}--- Submitting Job for $agent_id ---${NC}"
    payload="${US2_PAYLOADS[$agent_id]}"
    
    echo -e "${CYAN}Request Payload:${NC}"
    echo "$payload" | jq .
    
    job_id=$(create_bid_job "$payload")
    if [ -n "$job_id" ] && [ "$job_id" != "1" ]; then
        expected=$(echo "$payload" | jq '.bid_job_subject_ids | length')
        if poll_bids "$job_id" "$expected"; then
            fetch_task_results "$job_id" || echo -e "${RED}No winner was delivered for $agent_id.${NC}"
        fi
    else
        echo -e "${RED}Skipping polling for $agent_id due to creation failure.${NC}"
    fi
done

echo -e "\n${GREEN}All selected bid jobs processed successfully.${NC}"
