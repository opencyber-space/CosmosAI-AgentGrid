#!/usr/bin/env bash
set -euo pipefail

# entrypoint.sh - choose runtime behavior based on $AGENT
# If AGENT is not provided, default to 'default' and run agent.py
AGENT=${AGENT:-default}
export PYTHONPATH="/app:${PYTHONPATH:-}"

if [ -f /app/.env ]; then
  set -a
  source /app/.env
  set +a
fi

case "${AGENT}" in
  default)
    echo "Starting default agent (agent.py)"
    exec python3 agent.py
    ;;
  #for Function Demo
  doc-analyst-agent-001)
    echo "Starting doc-analyst-agent-001 agent (document_analysis_agent/nodes/sample_doc_analyst_agent.py)"
    exec python3 document_analysis_agent/nodes/sample_doc_analyst_agent.py
    ;;
    
  *)
    echo "Starting no agent for '${AGENT}' (unknown mapping)"
    #exec python3 agent.py --agent "${AGENT}"
    ;;
esac
