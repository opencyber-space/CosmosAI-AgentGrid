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


#if streamlit not installed pip3 install streamlit

#what this app does is 
#curl http://${PRIMARY_NODE_IP}:30608/subject-responses/by-subject/subj123   --> to get the human in loop interaction from agent
#curl -X POST http://${PRIMARY_NODE_IP}:30608/subject-responses/e81362ba-e31b-4ae4-b5c2-044f4e44b10d/set-response \
#  -H "Content-Type: application/json" \
#  -d '{
#        "response_data": { --> this is must, content of this object is user choice
#          "answer": "Artificial Intelligence is the simulation of human intelligence in machines.",
#          "confidence": 0.97,
#          "sources": ["wiki", "britannica"]
#        },
#        "status": "COMPLETED"  --> this is must
#      }'

streamlit run streamlit_his.py
