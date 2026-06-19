import time

try:
    from agents_sdk.core.metrics import get_registry, get_tracer, start_metrics_server
except ImportError:
    from metrics import get_registry, get_tracer, start_metrics_server


class AgentMetrics:
    def __init__(self, namespace="default"):
        start_metrics_server(port=9090)
        self.reg = get_registry(namespace=namespace)
        self.tracer = get_tracer()

        self._register_agents_metrics()

    def get_tracer(self):
        return self.tracer

    def _get_labels(self, user_task_id: str, task_id: str) -> dict:
        return {
            "user_task_id": user_task_id,
            "task_id": task_id
        }

    def _register_preprocess_metrics(self):
        # Preprocess Counters, Historgrams, Gauges
        self.reg.counter("agent_preprocess_skipped_total", "Tasks skipped during on_preprocess", labels=["reason", "user_task_id", "task_id"])
        self.reg.counter("agent_preprocess_errors_total", "Total preprocess errors", labels=["exception", "user_task_id", "task_id"])
        self.reg.counter("agent_preprocess_total", "Total preprocess calls", labels=["user_task_id", "task_id"])
        custom_buckets = [0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0]
        self.reg.histogram(
            "agent_preprocess_duration_seconds",
            "Duration of preprocess step in seconds",
            labels=["action", "exception", "user_task_id", "task_id"],
            buckets=custom_buckets
        )

    def _register_ondata_metrics(self):
        # on_data Counters, Historgrams, Gauges
        self.reg.gauge("agent_active_tasks", "Tasks currently executing inside on_data")
        self.reg.counter("agent_tasks_total", "Total tasks handled by on_data", labels=["status", "user_task_id", "task_id"])
        custom_buckets = [0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0]
        self.reg.histogram(
            "agent_ondata_duration_seconds",
            "Duration of on_data in seconds",
            labels=["action", "exception", "user_task_id", "task_id"],
            buckets=custom_buckets
        )

    def _register_toolcall_metrics(self):
        # Tools Call Counters, Historgrams, Gauges
        self.reg.counter("agent_tools_calls_total", "Total Tools calls", labels=["tool_id", "status", "user_task_id", "task_id"])
        self.reg.counter("agent_tools_error_total", "Total Tools errors", labels=["tool_id", "exception", "user_task_id", "task_id"])
        custom_buckets = [0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0]
        self.reg.histogram(
            "agent_tool_call_duration_seconds",
            "Duration of tool call in seconds",
            labels=["tool_id", "status", "user_task_id", "task_id"],
            buckets=custom_buckets
        )

    def _register_functioncall_metrics(self):
        # Function Call Counters, Historgrams, Gauges
        self.reg.counter("agent_function_calls_total", "Total agent-function calls", labels=["function_id", "status", "user_task_id", "task_id"])
        self.reg.counter("agent_function_calls_error_total", "Total agent-function errors calls", labels=["function_id", "exception", "user_task_id", "task_id"])
        custom_buckets = [0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0]
        self.reg.histogram(
            "agent_function_call_duration_seconds",
            "Duration of function call in seconds",
            labels=["function_id", "status", "user_task_id", "task_id"],
            buckets=custom_buckets
        )

    def _register_llmcall_metrics(self):
        # LLM Call Counters, Histograms
        self.reg.counter("agent_llm_calls_total", "Total LLM calls", labels=["model", "status", "who", "user_task_id", "task_id"])
        self.reg.counter("agent_llm_errors_total", "Total LLM call errors", labels=["model", "error_type", "who", "user_task_id", "task_id"])
        self.reg.counter("agent_llm_prompt_tokens_total", "Total prompt input tokens", labels=["model", "who", "user_task_id", "task_id"])
        self.reg.counter("agent_llm_completion_tokens_total", "Total completion output tokens", labels=["model", "who", "user_task_id", "task_id"])
        self.reg.counter("agent_llm_total_tokens_total", "Total tokens used", labels=["model", "who", "user_task_id", "task_id"])
        custom_buckets = [0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0]
        self.reg.histogram(
            "agent_llm_call_duration_seconds",
            "Duration of LLM calls in seconds",
            labels=["model", "status", "who", "user_task_id", "task_id"],
            buckets=custom_buckets
        )

    def _register_agents_metrics(self):
        # Info — static agent identity metadata (set once in __init__)
        self.reg.info("agent_identity", "Static identity information for this agent instance")
        # Enum — agent lifecycle state
        self.reg.enum(
            "agent_state",
            "Current lifecycle state of the agent",
            states=["initializing", "ready", "processing", "error"],
        )
        self._register_preprocess_metrics()
        self._register_ondata_metrics()
        self._register_toolcall_metrics()
        self._register_functioncall_metrics()
        self._register_llmcall_metrics()
        self.reg.info("task_mapping", "Mapping between user_task_id and task_id")

    def set_agent_state(self, state: str):
        self.reg.set_enum("agent_state", state)

    def set_agent_identity(self, subject_id, **kwargs):
        info = {"subject_id": subject_id, **kwargs}
        self.reg.set_info("agent_identity", info)

    #-----Preprocess metrics-----
    def increment_preprocess_errors(self, exception: str, user_task_id: str, task_id: str):
        ctx = self._get_labels(user_task_id, task_id)
        self.reg.inc("agent_preprocess_errors_total", amount=int(1), labels={"exception": exception, **ctx})

    def increment_preprocess_skipped(self, reason: str, user_task_id: str, task_id: str):
        ctx = self._get_labels(user_task_id, task_id)
        self.reg.inc("agent_preprocess_skipped_total", amount=int(1), labels={"reason": reason, **ctx})

    def increment_preprocess_total(self, user_task_id: str, task_id: str):
        ctx = self._get_labels(user_task_id, task_id)
        self.reg.inc("agent_preprocess_total", amount=int(1), labels={**ctx})

    def observe_histogram_preprocess(self, duration: float, action: str, exception: str, user_task_id: str, task_id: str):
        ctx = self._get_labels(user_task_id, task_id)
        self.reg.observe_histogram(
            "agent_preprocess_duration_seconds",
            duration,
            labels={"action": action, "exception": exception, **ctx}
        )

    #-----on_data metrics-----
    def increase_ondata_active_tasks(self):
        self.reg.inc_gauge("agent_active_tasks")

    def decrease_ondata_active_tasks(self):
        self.reg.dec_gauge("agent_active_tasks")

    def increase_tasks_total(self, status: str, user_task_id: str, task_id: str):
        ctx = self._get_labels(user_task_id, task_id)
        self.reg.inc("agent_tasks_total", amount=int(1), labels={"status": status, **ctx})

    def observe_histogram_ondata(self, duration: float, action: str, exception: str, user_task_id: str, task_id: str):
        ctx = self._get_labels(user_task_id, task_id)
        self.reg.observe_histogram(
            "agent_ondata_duration_seconds",
            duration,
            labels={"action": action, "exception": exception, **ctx}
        )

    #-----tools metrics-----
    def increase_toolcall_total(self, tool_id: str, status: str, user_task_id: str, task_id: str):
        ctx = self._get_labels(user_task_id, task_id)
        self.reg.inc("agent_tools_calls_total", amount=int(1), labels={"tool_id": tool_id, "status": status, **ctx})

    def increase_tool_error_total(self, tool_id: str, exception: str, user_task_id: str, task_id: str):
        ctx = self._get_labels(user_task_id, task_id)
        self.reg.inc("agent_tools_error_total", amount=int(1), labels={"tool_id": tool_id, "exception": exception, **ctx})

    def observe_histogram_toolcall_duration(self, tool_id: str, duration: float, status: str, user_task_id: str, task_id: str):
        ctx = self._get_labels(user_task_id, task_id)
        self.reg.observe_histogram(
            "agent_tool_call_duration_seconds",
            duration,
            labels={"tool_id": tool_id, "status": status, **ctx}
        )

    #-----function metrics-----
    def increase_function_calls_total(self, function_id: str, status: str, user_task_id: str, task_id: str):
        ctx = self._get_labels(user_task_id, task_id)
        self.reg.inc("agent_function_calls_total", amount=int(1), labels={"function_id": function_id, "status": status, **ctx})

    def increase_function_error_total(self, function_id: str, exception: str, user_task_id: str, task_id: str):
        ctx = self._get_labels(user_task_id, task_id)
        self.reg.inc("agent_function_calls_error_total", amount=int(1), labels={"function_id": function_id, "exception": exception, **ctx})

    def observe_histogram_function_duration(self, function_id: str, status: str, duration: float, user_task_id: str, task_id: str):
        ctx = self._get_labels(user_task_id, task_id)
        self.reg.observe_histogram(
            "agent_function_call_duration_seconds",
            duration,
            labels={"function_id": function_id, "status": status, **ctx}
        )

    #-----LLM metrics-----
    def increment_llm_calls(self, model: str, status: str, who: str, user_task_id: str, task_id: str):
        ctx = self._get_labels(user_task_id, task_id)
        self.reg.inc("agent_llm_calls_total", amount=int(1), labels={"model": model, "status": status, "who": who, **ctx})

    def increment_llm_errors(self, model: str, error_type: str, who: str, user_task_id: str, task_id: str):
        ctx = self._get_labels(user_task_id, task_id)
        self.reg.inc("agent_llm_errors_total", amount=int(1), labels={"model": model, "error_type": error_type, "who": who, **ctx})

    def increment_llm_prompt_tokens(self, model: str, count: int, who: str, user_task_id: str, task_id: str):
        ctx = self._get_labels(user_task_id, task_id)
        self.reg.inc("agent_llm_prompt_tokens_total", amount=count, labels={"model": model, "who": who, **ctx})

    def increment_llm_completion_tokens(self, model: str, count: int, who: str, user_task_id: str, task_id: str):
        ctx = self._get_labels(user_task_id, task_id)
        self.reg.inc("agent_llm_completion_tokens_total", amount=count, labels={"model": model, "who": who, **ctx})

    def increment_llm_total_tokens(self, model: str, count: int, who: str, user_task_id: str, task_id: str):
        ctx = self._get_labels(user_task_id, task_id)
        self.reg.inc("agent_llm_total_tokens_total", amount=count, labels={"model": model, "who": who, **ctx})

    def observe_llm_call_duration(self, model: str, status: str, duration: float, who: str, user_task_id: str, task_id: str):
        ctx = self._get_labels(user_task_id, task_id)
        self.reg.observe_histogram(
            "agent_llm_call_duration_seconds",
            duration,
            labels={"model": model, "status": status, "who": who, **ctx}
        )

    def record_task_mapping(self, user_task_id: str, task_id: str):
        self.reg.set_info("task_mapping", {"user_task_id": user_task_id, "task_id": task_id})