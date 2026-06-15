# schema-forge — Tool Documentation

Stateful local Python tool that **infers a strict JSON Schema (draft-07) from sample JSON or CSV**
using OpenAI. Also returns per-field documentation, business-logic validation rules, and data
quality issues spotted in the sample.

---

## Use-case

A data pipeline design agent receives a raw Kafka event sample or a CSV export and needs a formal
schema contract before wiring up downstream consumers. It calls this tool with the sample, gets back
a ready-to-use JSON Schema plus field-level docs, and can immediately validate future payloads or
generate TypeScript interfaces from the schema.

---

## Project layout

```
<tool-root-or-archive>
└── code/
    └── function.py    # defines class AgentSpaceV1Tool
```

---

## Configuration (`tool_data`)

| Key              | Type | Default           | Purpose                                                   |
|------------------|------|-------------------|-----------------------------------------------------------|
| `openai_api_key` | str  | `$OPENAI_API_KEY` | OpenAI key (env fallback supported)                       |
| `model`          | str  | `gpt-4o-mini`     | OpenAI model to use                                       |
| `strict_mode`    | bool | `true`            | Emit `additionalProperties:false`; mark all fields required |
| `persist_state`  | bool | `false`           | Enable save/load to disk                                  |
| `max_history`    | int  | `50`              | Bounded recent-call history length                        |
| `autosave_every` | int  | `0`               | Auto-save every N execute calls (0 = disabled)            |

---

## `execute(input_data) -> dict`

### Input

| Field         | Required | Description                                     |
|---------------|----------|-------------------------------------------------|
| `sample_data` | Yes      | Raw JSON (object or array) or CSV text          |
| `format`      | No       | `"json"` (default) or `"csv"`                   |
| `purpose`     | No       | What this data represents in plain English      |

### Output example

```json
{
  "ok": true,
  "tool_id": "agentspace.schema-forge.v1",
  "calls": 1,
  "op": "forge_schema",
  "schema_result": {
    "json_schema": {
      "$schema": "http://json-schema.org/draft-07/schema#",
      "type": "object",
      "additionalProperties": false,
      "required": ["user_id", "email", "created_at", "is_active"],
      "properties": {
        "user_id":    { "type": "integer" },
        "email":      { "type": "string", "format": "email" },
        "created_at": { "type": "string", "format": "date-time" },
        "is_active":  { "type": "boolean" }
      }
    },
    "field_docs": {
      "user_id":    "Unique integer identifier for the user.",
      "email":      "User's email address used for authentication.",
      "created_at": "ISO-8601 timestamp when the account was created.",
      "is_active":  "Whether the user account is currently active."
    },
    "validation_rules": [
      "email must be unique across all records",
      "created_at must not be a future timestamp"
    ],
    "quality_issues": [],
    "format_detected": "json"
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
    download_url="/path/to/schema-forge",
    tool_id="agentspace.schema-forge.v1",
    tool_data={"openai_api_key": "sk-...", "strict_mode": True}
)

sample = '{"order_id": 1001, "customer_id": 42, "amount": 99.99, "currency": "USD", "status": "paid"}'
result = tool.execute({"sample_data": sample, "format": "json", "purpose": "E-commerce order record"})

schema = result["schema_result"]["json_schema"]
docs   = result["schema_result"]["field_docs"]
print(json.dumps(schema, indent=2))
```
