# log-detective — Tool Documentation

Stateful local Python tool that **analyzes raw service logs** using OpenAI and returns a
structured incident diagnostic: anomaly list, error clusters, severity score, ranked root-cause
hypotheses, on-call recommendations, and a timeline summary.

---

## Use-case

An on-call automation agent receives a PagerDuty alert, pulls the last 300 log lines from the
affected service, feeds them to this tool, and gets an instant diagnostic briefing — including
a severity score and ranked root-cause hypotheses — before deciding whether to auto-remediate
or escalate to a human.

---

## Project layout

```
<tool-root-or-archive>
└── code/
    └── function.py    # defines class AgentSpaceV1Tool
```

---

## Configuration (`tool_data`)

| Key              | Type | Default       | Purpose                                            |
|------------------|------|---------------|----------------------------------------------------|
| `openai_api_key` | str  | `$OPENAI_API_KEY` | OpenAI key (env fallback supported)            |
| `model`          | str  | `gpt-4o-mini` | OpenAI model to use                                |
| `max_lines`      | int  | `300`         | Trims to last N lines before sending to model      |
| `persist_state`  | bool | `false`       | Enable save/load to disk                           |
| `max_history`    | int  | `50`          | Bounded recent-call history length                 |
| `autosave_every` | int  | `0`           | Auto-save every N execute calls (0 = disabled)     |

---

## `execute(input_data) -> dict`

### Input

| Field          | Required | Description                                      |
|----------------|----------|--------------------------------------------------|
| `logs`         | Yes      | Raw newline-separated log text                   |
| `service_name` | No       | Name of the service that emitted the logs        |
| `time_window`  | No       | e.g. `"2024-06-10 02:00-03:00 UTC"`              |

### Output example

```json
{
  "ok": true,
  "tool_id": "agentspace.log-detective.v1",
  "calls": 1,
  "op": "analyze_logs",
  "log_analysis": {
    "anomalies": [
      {"timestamp": "02:14:01Z", "message": "db: connection timeout after 30s", "category": "timeout"}
    ],
    "error_clusters": [
      {"label": "DB timeout loop", "count": 4, "sample_lines": ["ERROR db: connection timeout..."], "component": "database"}
    ],
    "severity_score": 8,
    "root_cause_hypotheses": [
      {"rank": 1, "hypothesis": "Database connection pool exhausted under load spike", "confidence": "high", "evidence": "4 consecutive timeouts followed by circuit breaker OPEN"}
    ],
    "recommendations": [
      "Check database max_connections and active queries",
      "Scale up connection pool or add a read replica",
      "Review circuit breaker thresholds"
    ],
    "timeline_summary": "DB timeouts began at 02:14:01Z, retries failed, circuit breaker opened at 02:14:34Z causing cascading 503s."
  },
  "history_len": 1,
  "persisted": false
}
```

---

## `execute_command(command_name, data) -> dict`

| Command     | Data                         | Returns                      |
|-------------|------------------------------|------------------------------|
| `set`       | `{"key": str, "value": any}` | `{ok, op:"set", key}`        |
| `get`       | `{"key": str}`               | `{ok, op:"get", key, value}` |
| `reset`     | `{}`                         | `{ok, op:"reset"}`           |
| `get_state` | `{}`                         | full state snapshot           |
| `save`      | `{}` (persist_state=true)    | `{ok, op:"save", path}`      |
| `load`      | `{}` (persist_state=true)    | `{ok, op:"load", state}`     |

---

## Quick-start

```python
tool = LocalToolExecutor(
    download_url="/path/to/log-detective",
    tool_id="agentspace.log-detective.v1",
    tool_data={"openai_api_key": "sk-...", "max_lines": 200}
)

logs = open("/var/log/payments-api/app.log").read()
result = tool.execute({"logs": logs, "service_name": "payments-api"})
analysis = result["log_analysis"]
print(f"Severity: {analysis['severity_score']}/10")
print(analysis["timeline_summary"])
for rec in analysis["recommendations"]:
    print("-", rec)
```
