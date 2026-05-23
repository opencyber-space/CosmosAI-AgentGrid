---
description: Steps to build, deploy, test, and debug the movie planner agents
---

# Movie Planner Test Workflow

This workflow provides the steps to build, deploy, test, and debug the Movie Planner agents.

## 1. Build and Deploy
Run the following script to build the agent images and deploy them to the cluster:
// turbo
```bash
bash agents_tests/kini_tests/agents_registration/6_human_in_loop_movie_planner/all.bash
```

## 2. Send Inference Request
Use the following script to trigger a movie planning request:
// turbo
```bash
bash agents_tests/kini_tests/agents_registration/6_human_in_loop_movie_planner/inference_request.sh
```

## 3. Monitor Agent Logs
If the output is `null` or incorrect, check the logs of the agents in the following sequence:

1. **Planner Agent**: `i1-movieplanner-planner-agent-*`
2. **Calendar Agent**: `i1-movieplanner-calendar-agent-*`
3. **Preference Agent**: `i1-movieplanner-preferences-agent-*`
4. **BookMyShow Agent (Aggregator)**: `i1-movieplanner-bookmyshow-agent-*`

### How to Check Logs
First, list the pods to get the exact names:
```bash
kubectl get pods -n agents | grep i1-movieplanner
```

Then, check the `agent-core` container for the specific pod (replace `<POD_NAME>`):
```bash
kubectl logs -f -n agents --tail 100 <POD_NAME> agent-core
```

## 4. Debugging
- If `inference_request.sh` returns `OUTPUT: null`, it indicates an error in the agent chain.
- Follow the logs in the sequence above to identify where the flow broke.
