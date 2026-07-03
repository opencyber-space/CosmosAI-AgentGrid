#!/bin/bash

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

kubectl get nodes -l nodeID --show-labels
# if above command shows empty, then add tag to node with nodeID lable
# for example 
# kubectl label nodes <node-name> nodeID=<value>

ACTION=${1:-""}
FRAMEDB_ID=${2:-"demo-instance-4"}

if [ "$ACTION" == "create" ]; then
    curl -X POST ${MEMORYGRID_GLOBAL_CONFIG}/global/framedb/instances \
      -H "Content-Type: application/json" \
      -d '{
        "framedb_id": "'"${FRAMEDB_ID}"'",
        "node_id": "node-1",
        "metadata": {"purpose": "demo"},
        "redis_config": ["maxmemory 256mb", "maxmemory-policy allkeys-lru"],
        "cluster_id": "local-cluster"
      }'
elif [ "$ACTION" == "delete" ]; then
    curl -X DELETE ${MEMORYGRID_GLOBAL_CONFIG}/global/framedb/instances/${FRAMEDB_ID}
elif [ "$ACTION" == "query" ]; then
    curl -X GET ${MEMORYGRID_GLOBAL_CONFIG}/global/framedb/instances/${FRAMEDB_ID}
else
    echo "Action not implemented or missing. Supported actions: create, delete, query"
    exit 1
fi