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


# Fetch the workflow execution URL
RESPONSE=$(curl -s "${API_BASE_URL}/api/runtime-workflows?workflow_uri=simple-memory-usage-workflow:1.0.0-stable&limit=20&skip=0")
WORKFLOW_URL=$(echo "$RESPONSE" | python3 -c 'import sys, json; print(json.load(sys.stdin)["data"][0]["url"])')

if [ -z "$WORKFLOW_URL" ]; then
    echo "Error: Could not retrieve workflow URL from response: $RESPONSE"
    exit 1
fi

echo "Executing workflow at $WORKFLOW_URL"

echo "Running Example 1"

text_to_post='Python is a high-level programming language. Python has a large standard library. The standard library contains modules for file I/O, networking, and data processing. Machine learning is a subset of artificial intelligence. Neural networks are the foundation of deep learning. Deep learning was pioneered by Geoffrey Hinton. Transformers are a type of neural network architecture. Attention mechanisms are the core of transformer models.'

payload=$(jq -n --arg text_to_post "$text_to_post" '{text: $text_to_post, document_id: "69467f65-5913-48cf-9172-8ac7630c0b38"}')
echo "$payload"

curl -X POST "$WORKFLOW_URL/api/execute" -H "Content-Type: application/json" \
-d "$payload" | json_pp

echo "--------------------------------------------------------"

echo "Running Example 2"
text_to_post='Python is widely used in data science and machine learning. TensorFlow is a deep learning framework. TensorFlow has Python bindings. Neural networks can learn from large datasets. Gradient descent is an optimization algorithm.'

payload=$(jq -n --arg text_to_post "$text_to_post" '{text: $text_to_post, document_id: "69467f65-5913-48cf-9172-8ac7630c0b39"}')
echo "$payload"

curl -X POST "$WORKFLOW_URL/api/execute" -H "Content-Type: application/json" \
-d "$payload" | json_pp

echo "--------------------------------------------------------"

echo "Running Example 3"
text_to_post='Olive oil is a healthy cooking fat. Garlic contains allicin. Tomatoes are rich in lycopene.'

payload=$(jq -n --arg text_to_post "$text_to_post" '{text: $text_to_post, document_id: "33367f65-5913-48cf-9172-8ac7630c0b39"}')
echo "$payload"

curl -X POST "$WORKFLOW_URL/api/execute" -H "Content-Type: application/json" \
-d "$payload" | json_pp