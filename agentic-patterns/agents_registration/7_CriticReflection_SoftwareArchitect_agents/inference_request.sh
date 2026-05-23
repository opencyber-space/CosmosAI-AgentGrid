
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
    \"subject_id\": \"software-agent\",
    \"session_id\": \"${session_id}\",
    \"task_id\": \"task-arch-001\",
    \"task_data\": {
      \"text\": \"Design a highly scalable, fault-tolerant, and high-performance distributed frame-sharing stack for short-lived frames of RTSP stream processing at scale. These are fast incoming frames with a short life cycle that will be discarded/deleted once processed.\\n\\nRequirements:\\n- Scope: The solution should focus EXCLUSIVELY on frame sharing. Ignore stream decoding or ingestion logic or anything else. Focus on the requirement: fast frame storage for a short life cycle, followed by immediate access and deletion.\\n- Concurrent Streams: Support 1,000+ live RTSP streams simultaneously.\\n- Frame Rate: Handle 5-25 FPS per stream (JPEG-encoded frames).\\n- Image Size: JPEG images vary from 300KB to 2MB when pushed to the stack.\\n- High Throughput: Provide ultra-fast read and write access for real-time processing.\\n- Distributed Architecture: The stack must scale across multiple nodes to leverage all available hardware in the cluster.\\n- Consumer Model: Support distributed AI models that fetch frames for inference and issue deletion commands once processing is complete.\\n- Resilience: Ensure the system is fault-tolerant and maintains performance under heavy workload.\\n- Open Source: All components finalized and chosen for the architecture MUST be available as open-source software.\",
      \"session_id\": \"${session_id}\",
      \"model_name\": \"aios:qwen3-1-7b-vllm-block\",
      \"communication_type\": \"p2p\"
    }
  }")

echo "=================================================="
echo "INPUT:"
echo "$RESPONSE" | jq -r '.ack.result.messages[0].message_data.job_data.text'

echo "=================================================="
echo "OUTPUT:"
echo "$RESPONSE" | jq -r '.output.job_output.text'
echo "=================================================="
