import json
import os
import time
import threading
import logging
from collections import deque
from typing import Any, Dict, Optional
from openai import OpenAI

logger = logging.getLogger(__name__)


class AgentSpaceV1Tool:
    """
    commit-scribe: generates Conventional Commit messages from git diffs using OpenAI.

    execute(input_data):
      input_data dict keys:
        - diff        (str, required) : output of `git diff` or `git diff --cached`
        - repo_context (str, optional): brief description of the repo/domain
        - branch_name  (str, optional): current branch name (helps infer scope/issue)

      returns:
        - commit_message: { type, scope, subject, body, breaking_changes[], suggested_issues[], full_message }
        - calls, history_len, tool_id

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
        self.convention = self.config.get("convention", "conventional-commits")

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
                logger.warning(f"[commit-scribe] Failed to load state: {e}")

        logger.info(f"[commit-scribe] Initialized tool_id={self.tool_id} model={self.model}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute(self, input_data: Any) -> Dict[str, Any]:
        with self._lock:
            self._calls += 1
            ts = time.time()

            if not isinstance(input_data, dict):
                raise ValueError("input_data must be a dict with at least 'diff' key.")

            diff = input_data.get("diff", "")
            if not diff:
                raise ValueError("'diff' is required and must be non-empty.")

            repo_context = input_data.get("repo_context", "")
            branch_name = input_data.get("branch_name", "")

            commit = self._generate_commit(diff, repo_context, branch_name)

            self._history.append({
                "timestamp": ts,
                "branch": branch_name,
                "type": commit.get("type"),
                "scope": commit.get("scope"),
                "subject": commit.get("subject"),
            })

            result = {
                "ok": True,
                "tool_id": self.tool_id,
                "calls": self._calls,
                "op": "generate_commit",
                "commit_message": commit,
                "history_len": len(self._history),
                "persisted": self._persist_enabled,
            }

            autosave_every = int(self.config.get("autosave_every", 0))
            if self._persist_enabled and autosave_every > 0 and self._calls % autosave_every == 0:
                try:
                    self._save_state_locked()
                    result["autosave"] = True
                except Exception as e:
                    logger.warning(f"[commit-scribe] Autosave failed: {e}")
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

    def _generate_commit(self, diff: str, repo_context: str, branch_name: str) -> Dict[str, Any]:
        convention_hint = (
            "Follow the Conventional Commits spec: <type>(<scope>): <subject>\n"
            "Types: feat, fix, docs, style, refactor, perf, test, build, ci, chore, revert\n"
            "- scope: inferred from changed file paths (e.g. auth, api, ui, db), or empty string\n"
            "- subject: imperative mood, lowercase, no trailing period, max 72 chars\n"
            "- body: explain WHY (not what), 2-4 sentences, or empty string\n"
            "- breaking_changes: list breaking changes introduced, or empty list\n"
            "- suggested_issues: inferred issue references like 'closes #42', or empty list\n"
        ) if self.convention == "conventional-commits" else (
            "Write a concise git commit message. Subject max 72 chars. Optional body explaining why.\n"
        )

        prompt = (
            "You are an expert software engineer who writes precise git commit messages.\n"
            f"{convention_hint}\n"
            "Analyze the git diff below and produce a commit message.\n\n"
            "Respond ONLY in this JSON format with no extra text:\n"
            "{\n"
            '  "type": "feat|fix|refactor|...",\n'
            '  "scope": "inferred-scope or empty string",\n'
            '  "subject": "imperative summary under 72 chars",\n'
            '  "body": "WHY this change was made (2-4 sentences) or empty string",\n'
            '  "breaking_changes": [],\n'
            '  "suggested_issues": [],\n'
            '  "full_message": "complete commit message ready to paste"\n'
            "}\n\n"
        )
        if repo_context:
            prompt += f"Repository context: {repo_context}\n\n"
        if branch_name:
            prompt += f"Branch: {branch_name}\n\n"
        prompt += f"Git diff:\n```diff\n{diff}\n```"

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        return json.loads(response.choices[0].message.content)

    # ------------------------------------------------------------------
    # State / persistence (same pattern as sample tool)
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
