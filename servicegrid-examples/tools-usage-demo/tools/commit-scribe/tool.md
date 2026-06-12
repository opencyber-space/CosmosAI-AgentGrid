# commit-scribe — Tool Documentation

Stateful local Python tool that **generates Conventional Commit messages from git diffs** using OpenAI.
Maintains call history, a KV store for context, and optional disk persistence.

---

## Use-case

An agent watching a CI pipeline can call this tool with `git diff --cached` output and get a
paste-ready, spec-compliant commit message — including detected type/scope, a body explaining *why*,
breaking change flags, and inferred issue references — without any manual writing.

---

## Project layout

```
<tool-root-or-archive>
└── code/
    └── function.py    # defines class AgentSpaceV1Tool
```

---

## Configuration (`tool_data`)

| Key              | Type   | Default                  | Purpose                                          |
|------------------|--------|--------------------------|--------------------------------------------------|
| `openai_api_key` | str    | `$OPENAI_API_KEY`        | OpenAI key (env fallback supported)              |
| `model`          | str    | `gpt-4o-mini`            | OpenAI model to use                              |
| `convention`     | str    | `conventional-commits`   | `"conventional-commits"` or `"freeform"`         |
| `persist_state`  | bool   | `false`                  | Enable save/load to disk                         |
| `max_history`    | int    | `50`                     | Bounded recent-call history length               |
| `autosave_every` | int    | `0`                      | Auto-save every N execute calls (0 = disabled)   |
| `counter_start`  | int    | `0`                      | Initial call counter value                       |

---

## `execute(input_data) -> dict`

### Input

| Field          | Required | Description                                         |
|----------------|----------|-----------------------------------------------------|
| `diff`         | Yes      | Output of `git diff` or `git diff --cached`         |
| `repo_context` | No       | Brief description of the repo/domain                |
| `branch_name`  | No       | Current branch name (helps infer scope and issues)  |

### Output example

```json
{
  "ok": true,
  "tool_id": "agentspace.commit-scribe.v1",
  "calls": 1,
  "op": "generate_commit",
  "commit_message": {
    "type": "fix",
    "scope": "auth",
    "subject": "raise AuthError when token is missing",
    "body": "Previously a missing token would fall through silently and cause a 500 downstream. Now we fail fast at the boundary.",
    "breaking_changes": [],
    "suggested_issues": ["closes #88"],
    "full_message": "fix(auth): raise AuthError when token is missing\n\nPreviously a missing token would fall through silently and cause a 500 downstream. Now we fail fast at the boundary.\n\ncloses #88"
  },
  "history_len": 1,
  "persisted": false
}
```

---

## `execute_command(command_name, data) -> dict`

| Command     | Data                            | Returns                     |
|-------------|---------------------------------|-----------------------------|
| `set`       | `{"key": str, "value": any}`    | `{ok, op:"set", key}`       |
| `get`       | `{"key": str}`                  | `{ok, op:"get", key, value}`|
| `reset`     | `{}`                            | `{ok, op:"reset"}`          |
| `get_state` | `{}`                            | full state snapshot          |
| `save`      | `{}` (persist_state=true)       | `{ok, op:"save", path}`     |
| `load`      | `{}` (persist_state=true)       | `{ok, op:"load", state}`    |

---

## Quick-start

```python
tool = LocalToolExecutor(
    download_url="/path/to/commit-scribe",
    tool_id="agentspace.commit-scribe.v1",
    tool_data={"openai_api_key": "sk-...", "model": "gpt-4o-mini"}
)

import subprocess
diff = subprocess.check_output(["git", "diff", "--cached"], text=True)
result = tool.execute({"diff": diff, "branch_name": "fix/token-validation"})
print(result["commit_message"]["full_message"])
```
