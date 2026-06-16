import time
from agents_sdk.core.metrics import get_registry, get_tracer, start_metrics_server

class AgentMetrics:
    def __init__(self, namespace="default"):
        #self.metrics = metrics

        start_metrics_server(port=9090)
        self.reg = get_registry(namespace=namespace)
        self.tracer = get_tracer()

        self._register_agents_metrics()

    def get_tracer(self):
        return self.tracer

    def _register_preprocess_metrics(self):
        # Preprocess Counters,Historgrams,Gauges
        self.reg.counter("agent_preprocess_skipped_total",   "Tasks skipped during on_preprocess",       labels=["reason"])
        self.reg.counter("agent_preprocess_errors_total", "Total preprocess errors", labels=["exception"])
        self.reg.counter("agent_preprocess_total", "Total preprocess calls")
        custom_buckets = [0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0]
        self.reg.histogram(
            "agent_preprocess_duration_seconds",
            "Duration of preprocess step in seconds",
            labels=["action", "exception"],
            buckets=custom_buckets
        )

    def _register_ondata_metrics(self):
        # on_data Counters,Historgrams,Gauges
        self.reg.gauge("agent_active_tasks", "Tasks currently executing inside on_data")
        self.reg.counter("agent_tasks_total",          "Total tasks handled by on_data",          labels=["status"])
        custom_buckets = [0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0]
        self.reg.histogram(
            "agent_ondata_duration_seconds",
            "Duration of on_data in seconds",
            labels=["action", "exception"],
            buckets=custom_buckets
        )

    def _register_toolcall_metrics(self):
        # Tools Call Counters,Historgrams,Gauges
        self.reg.counter("agent_tools_calls_total", "Total Tools calls",               labels=["tool_id", "status"])
        self.reg.counter("agent_tools_error_total", "Total Tools errors",               labels=["tool_id", "status"])
        custom_buckets = [0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0]
        self.reg.histogram(
            "agent_tool_call_duration_seconds",
            "Duration of tool call in seconds",
            labels=["tool_id", "status"],
            buckets=custom_buckets
        )
        
    def _register_functioncall_metrics(self):
        # Function Call Counters,Historgrams,Gauges
        self.reg.counter("agent_function_calls_total", "Total agent-function calls",               labels=["function_id", "status"])
        self.reg.counter("agent_function_calls_error_total", "Total agent-function errors calls",  labels=["function_id", "status"])
        custom_buckets = [0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0]
        
        self.reg.histogram(
            "agent_function_call_duration_seconds",
            "Duration of function call in seconds",
            labels=["function_id", "status"],
            buckets=custom_buckets
        )
    
    def _register_llmcall_metrics(self):
        # LLM Call Counters, Histograms
        self.reg.counter("agent_llm_calls_total", "Total LLM calls", labels=["model", "status"])
        self.reg.counter("agent_llm_errors_total", "Total LLM call errors", labels=["model", "error_type"])
        self.reg.counter("agent_llm_prompt_tokens_total", "Total prompt input tokens", labels=["model"])
        self.reg.counter("agent_llm_completion_tokens_total", "Total completion output tokens", labels=["model"])
        self.reg.counter("agent_llm_total_tokens_total", "Total tokens used", labels=["model"])
        
        custom_buckets = [0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0]
        
        self.reg.histogram(
            "agent_llm_call_duration_seconds",
            "Duration of LLM calls in seconds",
            labels=["model", "status"],
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

        # Summary — sliding-window quantiles for preprocess step
        # this is resource heavy, So avoiding summary unless necessary, for now using histogram
        # self.reg.summary("preprocess_latency_seconds", "Latency of the on_preprocess step")


    def set_agent_state(self, state: str):
        self.reg.set_enum("agent_state", state)

    def set_agent_identity(self, subject_id, **kwargs):
        info = {"subject_id": subject_id, **kwargs}
        self.reg.set_info("agent_identity", info)

    #-----Preprocess metrics-----    
    def increment_preprocess_errors(self, exception: str):
        self.reg.inc("agent_preprocess_errors_total", labels={"exception": exception})
        
    def increment_preprocess_skipped(self, reason: str):
        self.reg.inc("agent_preprocess_skipped_total", labels={"reason": reason})

    def increment_preprocess_total(self):
        self.reg.inc("agent_preprocess_total")

    def observe_histogram_preprocess(self, duration: float, action: str, exception: str):
        self.reg.observe_histogram(
            "agent_preprocess_duration_seconds",
            duration,
            labels={"action": action, "exception": exception}
        )

    #-----on_data metrics-----    
    def increase_ondata_active_tasks(self):
        self.reg.inc_gauge("agent_active_tasks")
        
    def decrease_ondata_active_tasks(self):
        self.reg.dec_gauge("agent_active_tasks")

    def increase_tasks_total(self, status: str):
        self.reg.inc("agent_tasks_total", labels={"status": status})

    def observe_histogram_ondata(self, duration: float, action: str, exception: str):
        self.reg.observe_histogram(
            "agent_ondata_duration_seconds",
            duration,
            labels={"action": action, "exception": exception}
        )

    #-----tools metrics----- 
    def increase_toolcall_total(self, tool_id: str, status: str):
        self.reg.inc("agent_tools_calls_total", labels={"tool_id": tool_id, "status": status})
    def increase_tool_error_total(self, tool_id: str, exception: str):
        self.reg.inc("agent_tools_error_total", labels={"tool_id": tool_id, "exception": exception})
    def observe_histogram_toolcall_duration(self, tool_id: str, duration: float, status: str):
        self.reg.observe_histogram(
            "agent_tool_call_duration_seconds",
            duration,
            labels={"tool_id": tool_id, "status": status}
        )

    #-----function metrics-----    
    def increase_function_calls_total(self, function_id: str, status: str):
        self.reg.inc("agent_function_calls_total", labels={"function_id": function_id, "status": status})
    
    def increase_function_error_total(self, function_id: str, exception: str):
        self.reg.inc("agent_function_calls_error_total", labels={"function_id": function_id, "exception": exception})
    
    def observe_histogram_function_duration(self, function_id: str, status: str, duration: float):
        self.reg.observe_histogram(
            "agent_function_call_duration_seconds",
            duration,
            labels={"function_id": function_id, "status": status}
        )


    #-----LLM metrics-----   
    def increment_llm_calls(self, model: str, status: str):
        self.reg.inc("agent_llm_calls_total", labels={"model": model, "status": status})

    def increment_llm_errors(self, model: str, error_type: str):
        self.reg.inc("agent_llm_errors_total", labels={"model": model, "error_type": error_type})

    def increment_llm_prompt_tokens(self, model: str, count: int):
        self.reg.inc("agent_llm_prompt_tokens_total", amount=count, labels={"model": model})

    def increment_llm_completion_tokens(self, model: str, count: int):
        self.reg.inc("agent_llm_completion_tokens_total", amount=count, labels={"model": model})

    def increment_llm_total_tokens(self, model: str, count: int):
        self.reg.inc("agent_llm_total_tokens_total", amount=count, labels={"model": model})

    def observe_llm_call_duration(self, model: str, status: str, duration: float):
        self.reg.observe_histogram(
            "agent_llm_call_duration_seconds",
            duration,
            labels={"model": model, "status": status}
        )


    