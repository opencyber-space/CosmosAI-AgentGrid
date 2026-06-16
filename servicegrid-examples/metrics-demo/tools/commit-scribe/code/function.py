import json
import os
import time
import threading
import logging
from collections import deque
from typing import Any, Dict, Optional
from openai import OpenAI
from google import genai

# Import AgentMetrics using a robust search for utils.metrics_util
try:
    from utils.metrics_util import AgentMetrics
except ImportError:
    import sys
    current_dir = os.path.dirname(os.path.abspath(__file__))
    temp_dir = current_dir
    for _ in range(5):
        if os.path.exists(os.path.join(temp_dir, "utils", "metrics_util.py")):
            sys.path.insert(0, temp_dir)
            break
        temp_dir = os.path.dirname(temp_dir)
    try:
        from utils.metrics_util import AgentMetrics
    except ImportError:
        class AgentMetricsFallback:
            def __init__(self, *args, **kwargs):
                pass
            def __getattr__(self, name):
                def method(*args, **kwargs):
                    pass
                return method
        AgentMetrics = AgentMetricsFallback

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
        self.client = None
        if api_key:
            self.client = OpenAI(api_key=api_key)
        self.model = self.config.get("model", "gpt-4o-mini")
        self.convention = self.config.get("convention", "conventional-commits")
        self.llm_paramteres={}

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

        self.metrics = AgentMetrics(namespace="commit_scribe")
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

            if "tool_model" in input_data:
                self._create_client(input_data["tool_model"])
                logger.info(f"[log-detective] Created client for tool_model={input_data['tool_model']['llm_block_id']}")

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

    def _create_client(self, model_dict: dict):
        model_type = model_dict["llm_type"]
        model_name = model_dict["llm_block_id"]
        api_key = model_dict["llm_parameters"].get("api_key")
        llm_parameters = dict(model_dict["llm_parameters"])
        llm_parameters.pop("api_key", None)
        
        mapped_params = {}
        if "openai" in model_name:
            self.model = model_name.split(":")[-1]
            self.client = OpenAI(api_key=api_key)
            
            if "max_completion_tokens" in llm_parameters:
                is_old = False
                if "gpt-3.5" in self.model:
                    is_old = True
                elif "gpt-4" in self.model and "gpt-4o" not in self.model:
                    is_old = True

                if is_old:
                    mapped_params["max_tokens"] = llm_parameters["max_completion_tokens"]
                else:
                    mapped_params["max_completion_tokens"] = llm_parameters["max_completion_tokens"]
            elif "max_tokens" in llm_parameters:
                is_old = False
                if "gpt-3.5" in self.model:
                    is_old = True
                elif "gpt-4" in self.model and "gpt-4o" not in self.model:
                    is_old = True

                if is_old:
                    mapped_params["max_tokens"] = llm_parameters["max_tokens"]
                else:
                    mapped_params["max_completion_tokens"] = llm_parameters["max_tokens"]

            if "top_p" in llm_parameters:
                mapped_params["top_p"] = llm_parameters["top_p"]
            if "temperature" in llm_parameters:
                mapped_params["temperature"] = llm_parameters["temperature"]

        elif "gemini" in model_name:
            self.model = model_name.split(":")[-1]
            self.client = genai.Client(api_key=api_key)

            if "max_completion_tokens" in llm_parameters:
                mapped_params["max_output_tokens"] = llm_parameters["max_completion_tokens"]
            elif "max_tokens" in llm_parameters:
                mapped_params["max_output_tokens"] = llm_parameters["max_tokens"]

            if "top_k" in llm_parameters:
                mapped_params["top_k"] = llm_parameters["top_k"]
            if "top_p" in llm_parameters:
                mapped_params["top_p"] = llm_parameters["top_p"]
            if "temperature" in llm_parameters:
                mapped_params["temperature"] = llm_parameters["temperature"]

        self.llm_paramteres = mapped_params


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
        if self.client is None:
            raise ValueError("LLM client not initialized. Please provide an API key.")

        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0
        start_time = time.time()

        try:
            if "gemini" in self.model:
                from google.genai import types
                config_args = {"response_mime_type": "application/json"}
                config_args.update(self.llm_paramteres)
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=types.GenerateContentConfig(**config_args),
                )
                duration = time.time() - start_time
                usage = getattr(response, "usage_metadata", None)
                if usage:
                    prompt_tokens = getattr(usage, "prompt_token_count", 0) or getattr(usage, "prompt_tokens", 0) or 0
                    completion_tokens = getattr(usage, "candidates_token_count", 0) or getattr(usage, "completion_tokens", 0) or 0
                    total_tokens = getattr(usage, "total_token_count", 0) or getattr(usage, "total_tokens", 0) or 0
                result_dict = json.loads(response.text)
            else:
                call_args = {
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "response_format": {"type": "json_object"},
                }
                call_args.update(self.llm_paramteres)
                response = self.client.chat.completions.create(**call_args)
                duration = time.time() - start_time
                usage = getattr(response, "usage", None)
                if usage:
                    prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
                    completion_tokens = getattr(usage, "completion_tokens", 0) or 0
                    total_tokens = getattr(usage, "total_tokens", 0) or 0
                result_dict = json.loads(response.choices[0].message.content)
            
            # Observe metrics for successful call
            self.metrics.increment_llm_calls(self.model, "success")
            self.metrics.observe_llm_call_duration(self.model, "success", duration)
            if prompt_tokens > 0:
                self.metrics.increment_llm_prompt_tokens(self.model, prompt_tokens)
            if completion_tokens > 0:
                self.metrics.increment_llm_completion_tokens(self.model, completion_tokens)
            if total_tokens > 0:
                self.metrics.increment_llm_total_tokens(self.model, total_tokens)
                
            return result_dict

        except Exception as e:
            duration = time.time() - start_time
            self.metrics.increment_llm_calls(self.model, "failed")
            self.metrics.increment_llm_errors(self.model, type(e).__name__)
            self.metrics.observe_llm_call_duration(self.model, "failed", duration)
            raise e

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
