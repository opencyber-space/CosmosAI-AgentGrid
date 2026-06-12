import json
import os
import time
import threading
import logging
from collections import deque
from typing import Any, Dict
from openai import OpenAI

logger = logging.getLogger(__name__)


class AgentSpaceV1Tool:
    """
    schema-forge: infers a strict JSON Schema (draft-07) from sample JSON or CSV
    data using OpenAI. Also returns per-field docs, extra validation rules, and
    data quality issues found in the sample.

    execute(input_data):
      input_data dict keys:
        - sample_data (str, required) : raw JSON or CSV sample
        - format      (str, optional) : "json" (default) or "csv"
        - purpose     (str, optional) : plain-English description of what this data is

      returns:
        - schema_result: { json_schema, field_docs{}, validation_rules[],
                           quality_issues[], format_detected }

    execute_command(command_name, data):
      set / get / reset / get_state / save / load
    """

    def __init__(self, tool_id: str, tool_data: Dict[str, Any]):
        self.tool_id = tool_id
        self.config = tool_data or {}

        api_key = (
            self.config.get("default_tool_usage_credentials", {}).get("openai_api_key")
            or self.config.get("openai_api_key")
            or os.environ.get("OPENAI_API_KEY", "")
        )
        self.client = OpenAI(api_key=api_key)
        self.model = self.config.get("model", "gpt-4o-mini")
        self.strict_mode = bool(self.config.get("strict_mode", True))

        self._calls = int(self.config.get("counter_start", 0))
        self._kv: Dict[str, Any] = {}
        self._history = deque(maxlen=int(self.config.get("max_history", 50)))
        self._lock = threading.RLock()

        self._persist_enabled = bool(self.config.get("persist_state", False))
        default_state_dir = os.path.join(
            os.environ.get("AGENTSPACE_STATE_ROOT", "/tmp/agentspace_state"),
            self.tool_id,
        )
        self._state_dir = str(self.config.get("state_dir", default_state_dir))
        self._state_file = os.path.join(self._state_dir, "state.json")

        if self._persist_enabled:
            try:
                self._load_state_locked()
            except FileNotFoundError:
                pass
            except Exception as e:
                logger.warning(f"[schema-forge] Failed to load state: {e}")

        logger.info(f"[schema-forge] Initialized tool_id={self.tool_id} model={self.model}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute(self, input_data: Any) -> Dict[str, Any]:
        with self._lock:
            self._calls += 1
            ts = time.time()

            if not isinstance(input_data, dict):
                raise ValueError("input_data must be a dict with at least 'sample_data' key.")

            sample_data = input_data.get("sample_data", "")
            if not sample_data:
                raise ValueError("'sample_data' is required and must be non-empty.")

            data_format = input_data.get("format", "json").lower()
            purpose = input_data.get("purpose", "")

            schema_result = self._forge_schema(sample_data, data_format, purpose)

            self._history.append({
                "timestamp": ts,
                "format": schema_result.get("format_detected"),
                "field_count": len(schema_result.get("field_docs", {})),
                "quality_issues": len(schema_result.get("quality_issues", [])),
            })

            result = {
                "ok": True,
                "tool_id": self.tool_id,
                "calls": self._calls,
                "op": "forge_schema",
                "schema_result": schema_result,
                "history_len": len(self._history),
                "persisted": self._persist_enabled,
            }

            autosave_every = int(self.config.get("autosave_every", 0))
            if self._persist_enabled and autosave_every > 0 and self._calls % autosave_every == 0:
                try:
                    self._save_state_locked()
                    result["autosave"] = True
                except Exception as e:
                    logger.warning(f"[schema-forge] Autosave failed: {e}")
                    result["autosave"] = False

            return result

    def execute_command(self, command_name: str, data: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            name = (command_name or "").strip().lower()
            data = data or {}

            if name == "set":
                key = str(data.get("key"))
                if key == "None":
                    raise ValueError("Missing 'key' for set command")
                self._kv[key] = data.get("value")
                return {"ok": True, "op": "set", "key": key}

            elif name == "get":
                key = str(data.get("key"))
                if key == "None":
                    raise ValueError("Missing 'key' for get command")
                return {"ok": True, "op": "get", "key": key, "value": self._kv.get(key)}

            elif name == "reset":
                self._kv.clear()
                self._history.clear()
                self._calls = 0
                return {"ok": True, "op": "reset"}

            elif name == "get_state":
                return self._snapshot()

            elif name == "save":
                if not self._persist_enabled:
                    return {"ok": False, "error": "persistence_disabled"}
                self._save_state_locked()
                return {"ok": True, "op": "save", "path": self._state_file}

            elif name == "load":
                if not self._persist_enabled:
                    return {"ok": False, "error": "persistence_disabled"}
                self._load_state_locked()
                return {"ok": True, "op": "load", "path": self._state_file, "state": self._snapshot()}

            else:
                raise ValueError(f"Unknown command: {command_name}")

    # ------------------------------------------------------------------
    # OpenAI call
    # ------------------------------------------------------------------

    def _forge_schema(self, sample_data: str, data_format: str, purpose: str) -> Dict[str, Any]:
        format_hint = (
            "The sample is JSON. Infer a strict JSON Schema (draft-07) from it."
            if data_format == "json"
            else "The sample is CSV. Infer a JSON Schema (draft-07) for one row-object, mapping each column header to a typed property."
        )

        strict_hint = (
            'Set "additionalProperties": false on all objects. Mark every observed field as required unless clearly optional (e.g. nullable or absent in some rows).'
            if self.strict_mode
            else 'Use "additionalProperties": true and only mark fields required when clearly mandatory.'
        )

        prompt = (
            "You are an expert data engineer and JSON Schema author.\n"
            f"{format_hint}\n"
            f"Strictness rule: {strict_hint}\n\n"
            "Produce the following in your response:\n"
            "1. json_schema: a valid JSON Schema draft-07 object\n"
            "2. field_docs: dict mapping each field path (dot-notation for nested) to a one-sentence description\n"
            "3. validation_rules: list of business-logic constraints that go beyond JSON Schema (e.g. 'amount must be > 0 when status is paid')\n"
            "4. quality_issues: data quality problems spotted in the sample (inconsistent types, nulls where not expected, mixed date formats, etc.)\n"
            "5. format_detected: 'json' or 'csv'\n\n"
            "Respond ONLY in this JSON format with no extra text:\n"
            "{\n"
            '  "json_schema": { ... },\n'
            '  "field_docs": { "field.path": "description", ... },\n'
            '  "validation_rules": ["rule 1", "rule 2"],\n'
            '  "quality_issues": ["issue 1", "issue 2"],\n'
            '  "format_detected": "json"\n'
            "}\n\n"
        )
        if purpose:
            prompt += f"Intended purpose: {purpose}\n\n"
        prompt += f"Sample data:\n```\n{sample_data}\n```"

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        return json.loads(response.choices[0].message.content)

    # ------------------------------------------------------------------
    # State / persistence
    # ------------------------------------------------------------------

    def _snapshot(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "tool_id": self.tool_id,
            "calls": self._calls,
            "kv": dict(self._kv),
            "history_len": len(self._history),
            "persisted": self._persist_enabled,
            "state_dir": self._state_dir if self._persist_enabled else None,
        }

    def _ensure_state_dir(self):
        os.makedirs(self._state_dir, exist_ok=True)

    def _save_state_locked(self):
        self._ensure_state_dir()
        payload = {
            "calls": self._calls,
            "kv": self._kv,
            "history": list(self._history),
            "saved_at": time.time(),
        }
        with open(self._state_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def _load_state_locked(self):
        with open(self._state_file, "r", encoding="utf-8") as f:
            payload = json.load(f)
        self._calls = int(payload.get("calls", 0))
        self._kv = dict(payload.get("kv", {}))
        self._history.clear()
        for item in payload.get("history", []):
            self._history.append(item)
