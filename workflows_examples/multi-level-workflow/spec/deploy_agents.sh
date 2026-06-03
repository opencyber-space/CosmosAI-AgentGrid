
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
  "subject_id": "agent-workflow-loan-risk-router",
  "allocation": {
    "delegate_api_url": "${DELEGATE_API_URL}",
    "instances": [
      {
        "instance_id": "i1",
        "subject_id": "agent-workflow-loan-risk-router"
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
  "subject_id": "agent-workflow-financial-profile",
  "allocation": {
    "delegate_api_url": "${DELEGATE_API_URL}",
    "instances": [
      {
        "instance_id": "i1",
        "subject_id": "agent-workflow-financial-profile"
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
  "subject_id": "agent-workflow-market-risk",
  "allocation": {
    "delegate_api_url": "${DELEGATE_API_URL}",
    "instances": [
      {
        "instance_id": "i1",
        "subject_id": "agent-workflow-market-risk"
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
  "subject_id": "agent-workflow-collateral-evaluator",
  "allocation": {
    "delegate_api_url": "${DELEGATE_API_URL}",
    "instances": [
      {
        "instance_id": "i1",
        "subject_id": "agent-workflow-collateral-evaluator"
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
  "subject_id": "agent-workflow-loan-decision",
  "allocation": {
    "delegate_api_url": "${DELEGATE_API_URL}",
    "instances": [
      {
        "instance_id": "i1",
        "subject_id": "agent-workflow-loan-decision"
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
  "subject_id": "agent-workflow-transaction-history",
  "allocation": {
    "delegate_api_url": "${DELEGATE_API_URL}",
    "instances": [
      {
        "instance_id": "i1",
        "subject_id": "agent-workflow-transaction-history"
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
  "subject_id": "agent-workflow-identity-verification",
  "allocation": {
    "delegate_api_url": "${DELEGATE_API_URL}",
    "instances": [
      {
        "instance_id": "i1",
        "subject_id": "agent-workflow-identity-verification"
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
  "subject_id": "agent-workflow-fraud-score",
  "allocation": {
    "delegate_api_url": "${DELEGATE_API_URL}",
    "instances": [
      {
        "instance_id": "i1",
        "subject_id": "agent-workflow-fraud-score"
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
