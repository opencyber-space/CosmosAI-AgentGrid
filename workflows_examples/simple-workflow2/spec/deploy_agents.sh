
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

#/bin/bash

curl -X POST "${API_BASE_URL}/api/deploy-agent/deployer-123" \
-H "Content-Type: application/json" \
-d @- <<EOF
{
  "subject_id": "clause-extractor-agent-2",
  "allocation": {
    "delegate_api_url": "${DELEGATE_API_URL}",
    "instances": [
      {
        "instance_id": "i1",
        "subject_id": "clause-extractor-agent-2"
      }
    ],
    "meshes": [
      {
        "mesh_id": "mesh-a",
        "url": "${NATS_URL}"
      }
    ]
  }
}
EOF

curl -X POST "${API_BASE_URL}/api/deploy-agent/deployer-123" \
-H "Content-Type: application/json" \
-d @- <<EOF
{
  "subject_id": "compliance-checker-agent-2",
  "allocation": {
    "delegate_api_url": "${DELEGATE_API_URL}",
    "instances": [
      {
        "instance_id": "i1",
        "subject_id": "compliance-checker-agent-2"
      }
    ],
    "meshes": [
      {
        "mesh_id": "mesh-a",
        "url": "${NATS_URL}"
      }
    ]
  }
}
EOF

curl -X POST "${API_BASE_URL}/api/deploy-agent/deployer-123" \
-H "Content-Type: application/json" \
-d @- <<EOF
{
  "subject_id": "legal-memo-agent-2",
  "allocation": {
    "delegate_api_url": "${DELEGATE_API_URL}",
    "instances": [
      {
        "instance_id": "i1",
        "subject_id": "legal-memo-agent-2"
      }
    ],
    "meshes": [
      {
        "mesh_id": "mesh-a",
        "url": "${NATS_URL}"
      }
    ]
  }
}
EOF

curl -X POST "${API_BASE_URL}/api/deploy-agent/deployer-123" \
-H "Content-Type: application/json" \
-d @- <<EOF
{
  "subject_id": "negotiation-adviser-agent-2",
  "allocation": {
    "delegate_api_url": "${DELEGATE_API_URL}",
    "instances": [
      {
        "instance_id": "i1",
        "subject_id": "negotiation-adviser-agent-2"
      }
    ],
    "meshes": [
      {
        "mesh_id": "mesh-a",
        "url": "${NATS_URL}"
      }
    ]
  }
}
EOF

curl -X POST "${API_BASE_URL}/api/deploy-agent/deployer-123" \
-H "Content-Type: application/json" \
-d @- <<EOF
{
  "subject_id": "risk-identifier-agent-2",
  "allocation": {
    "delegate_api_url": "${DELEGATE_API_URL}",
    "instances": [
      {
        "instance_id": "i1",
        "subject_id": "risk-identifier-agent-2"
      }
    ],
    "meshes": [
      {
        "mesh_id": "mesh-a",
        "url": "${NATS_URL}"
      }
    ]
  }
}
EOF

curl -X POST "${API_BASE_URL}/api/deploy-agent/deployer-123" \
-H "Content-Type: application/json" \
-d @- <<EOF
{
  "subject_id": "simple-workflow-router-agent",
  "allocation": {
    "delegate_api_url": "${DELEGATE_API_URL}",
    "instances": [
      {
        "instance_id": "i1",
        "subject_id": "simple-workflow-router-agent"
      }
    ],
    "meshes": [
      {
        "mesh_id": "mesh-a",
        "url": "${NATS_URL}"
      }
    ]
  }
}
EOF
