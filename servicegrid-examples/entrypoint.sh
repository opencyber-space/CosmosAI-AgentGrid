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
  agent-code-creator-demo1-functions)
    echo "Starting agent-code-creator-demo1-functions agent (functions-usage-demo/nodes/agent_functions_code_creator.py)"
    exec python3 functions-usage-demo/nodes/agent_functions_code_creator.py
    ;;

  agent-code-reviewer-demo1-functions)
    echo "Starting agent-code-reviewer-demo1-functions agent (functions-usage-demo/nodes/agent_functions_reviewer.py)"
    exec python3 functions-usage-demo/nodes/agent_functions_reviewer.py
    ;;

  #for Tool Usage Demo
  agent-tool-user-demo)
    echo "Starting agent-tool-user-demo agent (tools-usage-demo/nodes/agent_tools_user.py)"
    exec python3 tools-usage-demo/nodes/agent_tools_user.py
    ;;

  #for Metrics Usage Demo using Tool Usage Demo Agent
  agent-tool-metrics-demo)
    echo "Starting agent-tool-metrics-demo agent (metrics-demo/nodes/agent_tool_metrics_demo.py)"
    exec python3 metrics-demo/nodes/agent_tool_metrics_demo.py
    ;;

  #for Metrics Usage Demo with Functions
  agent-code-creator-metrics-in-functions)
    echo "Starting agent-code-creator-metrics-in-functions agent (metrics-demo-with-functions/nodes/agent_functions_code_creator.py)"
    exec python3 metrics-demo-with-functions/nodes/agent_functions_code_creator.py
    ;;

  agent-code-reviewer-metrics-in-functions)
    echo "Starting agent-code-reviewer-metrics-in-functions agent (metrics-demo-with-functions/nodes/agent_functions_reviewer.py)"
    exec python3 metrics-demo-with-functions/nodes/agent_functions_reviewer.py
    ;;
    
  *)
    echo "Starting no agent for '${AGENT}' (unknown mapping)"
    #exec python3 agent.py --agent "${AGENT}"
    ;;
esac
