---
description: Steps to build, deploy, test, and debug the architecture debater agents
---

# Architecture Debater Test Workflow

This workflow provides the steps to build, deploy, test, and debug the Software Architecture Debater agents.

## 1. Build and Deploy
Run the following script to build the agent images and deploy them to the cluster:
// turbo
```bash
bash agents_tests/kini_tests/agents_registration/7_CriticReflection_SoftwareArchitect_agents/all.bash
```

## 2. Send Inference Request
Use the following script to trigger a software architecture design request:
// turbo
```bash
bash agents_tests/kini_tests/agents_registration/7_CriticReflection_SoftwareArchitect_agents/inference_request.sh
```

## 3. Monitor Agent Logs
If the output is `null` or incorrect, check the logs of the agents in the following sequence:

1. **Software Agent (Generator)**: `i1-software-agent-*`
2. **Senior Architect Agent (Evaluator)**: `i1-senior-architect-agent-*`

### How to Check Logs
First, list the pods to get the exact names:
```bash
kubectl get pods -n agents | grep -E "i1-software-agent|i1-senior-architect-agent"
```

Then, check the `agent-core` container for the specific pod (replace `<POD_NAME>`):
```bash
kubectl logs -f -n agents --tail 100 <POD_NAME> agent-core
```

## 4. Debugging
- If `inference_request.sh` returns `OUTPUT: null`, it indicates an error in the agent chain or loop.
- Follow the logs in the sequence above to identify where the flow broke or if the loop is reaching maximum iterations.
