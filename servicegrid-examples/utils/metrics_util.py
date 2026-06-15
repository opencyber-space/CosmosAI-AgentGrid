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
        self.reg.counter("preprocess_skipped_total",   "Tasks skipped during on_preprocess",       labels=["reason"])
        self.reg.counter("preprocess_errors_total", "Total preprocess errors", labels=["exception"])
        self.reg.counter("preprocess_total", "Total preprocess calls")
        # Generates: [0.001, 0.008, 0.064, 0.512, 4.096, 32.768, 262.144, 2097.152...]
        # Formula: start * (factor ** i)
        auto_buckets = [round(0.001 * (8 ** i), 4) for i in range(10)]
        #auto_buckets = [0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0,100.0,500.0]
        self.reg.histogram(
            "preprocess_duration_seconds",
            "Duration of preprocess step in seconds",
            labels=["action", "exception"],
            buckets=auto_buckets
        )

    def _register_ondata_metrics(self):
        # on_data Counters,Historgrams,Gauges
        self.reg.gauge("active_tasks", "Tasks currently executing inside on_data")
        self.reg.counter("tasks_total",          "Total tasks handled by on_data",          labels=["status"])
        # Generates: [0.001, 0.008, 0.064, 0.512, 4.096, 32.768, 262.144, 2097.152...]
        # Formula: start * (factor ** i)
        auto_buckets = [round(0.001 * (8 ** i), 4) for i in range(10)]
        #auto_buckets = [0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0,100.0,500.0]
        self.reg.histogram(
            "ondata_duration_seconds",
            "Duration of on_data in seconds",
            labels=["action", "exception"],
            buckets=auto_buckets
        )

    def _register_toolcall_metrics(self):
        # Tools Call Counters,Historgrams,Gauges
        self.reg.counter("tools_calls_total", "Total Tools calls",               labels=["tool_id", "status"])
        self.reg.counter("tools_error_total", "Total Tools errors",               labels=["tool_id", "status"])
        # Generates: [0.001, 0.008, 0.064, 0.512, 4.096, 32.768, 262.144, 2097.152...]
        # Formula: start * (factor ** i)
        auto_buckets = [round(0.001 * (8 ** i), 4) for i in range(10)]
        #auto_buckets = [0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0,100.0,500.0]
        self.reg.histogram(
            "tool_call_duration_seconds",
            "Duration of tool call in seconds",
            labels=["tool_id", "status"],
            buckets=auto_buckets
        )
        
    def _register_functioncall_metrics(self):
        # Function Call Counters,Historgrams,Gauges
        self.reg.counter("function_calls_total", "Total agent-function calls",               labels=["function_id", "status"])
        self.reg.counter("function_calls_error_total", "Total agent-function errors calls",  labels=["function_id", "status"])
        # Generates: [0.001, 0.008, 0.064, 0.512, 4.096, 32.768, 262.144, 2097.152...]
        # Formula: start * (factor ** i)
        auto_buckets = [round(0.001 * (8 ** i), 4) for i in range(10)]
        #auto_buckets = [0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0,100.0,500.0]
        
        self.reg.histogram(
            "function_call_duration_seconds",
            "Duration of function call in seconds",
            labels=["function_id", "status"],
            buckets=auto_buckets
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
        self.reg.inc("preprocess_errors_total", labels={"exception": exception})
        
    def increment_preprocess_skipped(self, reason: str):
        self.reg.inc("preprocess_skipped_total", labels={"reason": reason})

    def increment_preprocess_total(self):
        self.reg.inc("preprocess_total")

    def observe_histogram_preprocess(self, duration: float, action: str, exception: str):
        self.reg.observe_histogram(
            "ondata_duration_seconds",
            duration,
            labels={"action": action, "exception": exception}
        )

    #-----on_data metrics-----    
    def increase_ondata_active_tasks(self):
        self.reg.inc_gauge("active_tasks")
        
    def decrease_ondata_active_tasks(self):
        self.reg.dec_gauge("active_tasks")

    def increase_tasks_total(self, status: str):
        self.reg.inc("tasks_total", labels={"status": status})

    def observe_histogram_ondata(self, duration: float, action: str, exception: str):
        self.reg.observe_histogram(
            "preprocess_duration_seconds",
            duration,
            labels={"action": action, "exception": exception}
        )

    #-----tools metrics----- 
    def increase_toolcall_total(self, tool_id: str, status: str):
        self.reg.inc("tools_calls_total", labels={"tool_id": tool_id, "status": status})
    def increase_tool_error_total(self, tool_id: str, exception: str):
        self.reg.inc("tools_error_total", labels={"tool_id": tool_id, "exception": exception})
    def observe_histogram_toolcall_duration(self, tool_id: str, duration: float, status: str):
        self.reg.observe_histogram(
            "tool_duration_seconds",
            duration,
            labels={"tool_id": tool_id, "status": status}
        )

    #-----function metrics-----    
    def increase_function_calls_total(self, function_id: str, status: str):
        self.reg.inc("function_calls_total", labels={"function_id": function_id, "status": status})
    
    def increase_function_error_total(self, function_id: str, exception: str):
        self.reg.inc("function_calls_error_total", labels={"function_id": function_id, "exception": exception})
    
    def observe_histogram_function_duration(self, function_id: str, status: str, duration: float):
        self.reg.observe_histogram(
            "function_duration_seconds",
            duration,
            labels={"function_id": function_id, "status": status}
        )


    