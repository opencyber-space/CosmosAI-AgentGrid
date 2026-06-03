#!/bin/bash
GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$GIT_ROOT" ]; then GIT_ROOT=$(pwd); fi
if [ -f "$GIT_ROOT/.env" ]; then set -a; source "$GIT_ROOT/.env"; set +a; else echo "Error: .env file MUST be present at $GIT_ROOT"; exit 1; fi

# User should list the graph JSON files to process here
GRAPHS=("graph.json")

for GRAPH in "${GRAPHS[@]}"; do
    if [ -f "$GRAPH" ]; then
        # Safely extract graph_name, graph_version, and graph_release_tag from the JSON file using python3
        NAME=$(python3 -c "import json, sys; print(json.load(open(sys.argv[1]))['graph_name'])" "$GRAPH")
        VERSION=$(python3 -c "import json, sys; print(json.load(open(sys.argv[1]))['graph_version'])" "$GRAPH")
        RELEASE_TAG=$(python3 -c "import json, sys; print(json.load(open(sys.argv[1]))['graph_release_tag'])" "$GRAPH")
        
        echo "Unregistering ${NAME}:${VERSION}-${RELEASE_TAG}..."
        curl -s -X DELETE "${POLICY_DB_URL}/graphs/${NAME}:${VERSION}-${RELEASE_TAG}" | json_pp
        echo -e "\nUnregistration completed for $GRAPH"
    else
        echo "Warning: Graph file '$GRAPH' not found, skipping..."
    fi
done