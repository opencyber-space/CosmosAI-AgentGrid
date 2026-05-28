
GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$GIT_ROOT" ]; then
    GIT_ROOT=$(pwd) # Fallback if not run within git
fi
if [ -f "$GIT_ROOT/.env" ]; then
    set -a; source "$GIT_ROOT/.env"; set +a
else
    echo "Error: .env file MUST be present at $GIT_ROOT"
    exit 1
fi

session_id="sess-$(printf "%05d" $((RANDOM % 100000)))"
echo "Using session_id: ${session_id}"

RESPONSE=$(curl -s -X POST ${DELEGATE_API_URL}/api/submit-and-wait \
 -H "Content-Type: application/json" \
 -d "{
    \"subject_id\": \"rfc-summarizer\",
    \"session_id\": \"${session_id}\",
    \"task_id\": \"task-003\",
    \"task_data\": {\"text\":\"Title: Add Canary Deployments to Service X\n\nContext: Service X currently uses blue/green deployments on Kubernetes. Rollbacks work but cost is high because two full environments are kept warm.\n\nGoals:\n\n1. Reduce deployment risk for weekly releases.\n\n2. Lower infra cost during rollouts.\n\n3. Improve observability of release impact.\n\nNon-goals:\n\n1. Rewriting CI/CD system.\n\n2. Changing service API or data model.\n\nProposal:\n\n1. Introduce canary strategy using 5% > 25% > 50% > 100% traffic steps over 60 minutes.\n\nUse Kubernetes Service mesh routing (virtual service rules) for traffic splitting.\n\nTrack SLIs: error_rate, p95_latency, and saturation (CPU/mem).\n\nDefine SLOs during canary: error_rate ≤ 1.5x baseline, p95_latency ≤ 1.3x baseline.\n\nAbort on breach for 10 consecutive minutes; auto-rollback to previous stable.\n\nKey Changes:\n\nAdd progressive traffic policy and rollout controller config.\n\nEmit release markers to metrics and logs.\n\nAdd alert rules tied to canary SLOs.\n\nAssumptions:\n\nBaseline metrics for last 7 days are available.\n\nMesh supports weighted routing in target cluster.\n\nOn-call can approve/abort during business hours.\n\nOpen Questions:\n\nDo we need synthetic checks in addition to live traffic?\n\nShould we stage canary only for read paths initially?\n\nRisks:\n\nPartial exposure may hide rare write-path regressions.\n\nTraffic mirroring could amplify cost if misconfigured.\n\nSuccess Criteria:\n\nTwo consecutive weekly releases without SLO breach.\n\nInfra cost during rollout reduced by ≥ 20% vs blue/green.\n\nMTTR for failed releases ≤ 15 minutes.\"
,\"session_id\": \"${session_id}\",\"model_name\":\"gemini:gemini-3.1-flash-lite\", \"communication_type\":\"direct\"}
  }")

# Extract Input and Output
INPUT=$(echo "$RESPONSE" | jq -r '.ack.result.messages[0].message_data.job_data.text // "No Input Found"')
OUTPUT=$(echo "$RESPONSE" | jq -r '.output.job_output.text // "No Output Found"')

# Print colorized
echo -e "\033[0;34mINPUT:\033[0m"
echo -e "\033[0;34m$INPUT\033[0m"
echo ""
echo -e "\033[0;32mOUTPUT:\033[0m"
echo -e "\033[0;32m$OUTPUT\033[0m"