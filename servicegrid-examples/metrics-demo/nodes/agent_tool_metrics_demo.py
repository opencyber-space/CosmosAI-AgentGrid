import time
import logging
import copy
from typing import List, Optional

from agents_sdk.core.agent_executor import AgentResult, AgentTask, Context
from agents_sdk.core.main import main
from agents_sdk.core.his import HisClient
from agents_functions import AgentFunctions
from agents_tools import AgentTools
from utils.metrics_util import AgentMetrics

log = logging.getLogger(__name__)

NODE_ID_MAPPING = {
    "agent-tool-user-demo": "my-agent-tool-user-demo"
}

NODE_TOOL_DEMO = "my-agent-tool-user-demo"

class ToolUsageDemoAgent:
    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        subject_id = getattr(self.subject.identity, 'subject_id', 'unknown')
        subject_version = getattr(self.subject.identity, 'subject_version', {"version": "1.0.0","release_tag": "stable"})
        if type(subject_version) != dict:
            subject_version = subject_version.to_dict()
        namespace = f"{subject_id}:{subject_version.get('version', 'unknown')}-{subject_version.get('release_tag', 'unknown')}"
        self.metrics = AgentMetrics(namespace=namespace)

        self.metrics.set_agent_state("initializing")
        
        # Extract functions configuration from config.parameters.FUNCTIONS_CONFIG
        config_params = getattr(self.subject.persona, 'config', {}).get("parameters", {}) if hasattr(self.subject, 'persona') else {}
        tools_config = config_params.get("TOOLS_CONFIG", {})
        tools_registry_url = tools_config.get("tools_registry_url")
        self.llm_block_id = tools_config.get("llm_block_id")

        # Extract openai_api_key from models.llm_parameters
        self.api_key = ""
        integrations = getattr(self.subject, 'integrations', None)
        models = getattr(integrations, 'models', []) if integrations else []
        self.selected_tool_model = {}
        for model in models:
            if self.llm_block_id == model.llm_block_id:
                self.selected_tool_model = model
                if type(self.selected_tool_model) != dict:
                    self.selected_tool_model = self.selected_tool_model.to_dict()
                llm_params = getattr(model, 'llm_parameters', {}) if hasattr(model, 'llm_parameters') else (model.get('llm_parameters', {}) if isinstance(model, dict) else {})
                if "api_key" in llm_params:
                    self.api_key = llm_params["api_key"]
                    break

        if not self.api_key:
            raise Exception("API key not found")
        if not tools_registry_url:
            raise Exception("Tools registry URL not found")
        if not self.llm_block_id:
            raise Exception("LLM block ID not found")

        if "openai:" in self.llm_block_id:
            model_name = self.llm_block_id.replace("openai:", "")
            self.tools = AgentTools(tools_db_url=tools_registry_url, openai_api_key=self.api_key, gemini_api_key=None, model_name=model_name)
        elif "gemini:" in self.llm_block_id:
            model_name = self.llm_block_id.replace("gemini:", "")
            self.tools = AgentTools(tools_db_url=tools_registry_url, openai_api_key=None, gemini_api_key=self.api_key, model_name=model_name)

        # Register all tools upfront so their runtimes are ready before any search.
        subject_tools = getattr(integrations, 'subject_tools', []) if integrations else []
        self.tool_commit_scribe = ""
        self.tool_log_detective = ""
        self.tool_schema_forge = ""
        for tool_ in subject_tools:
            if type(tool_) != dict:
                tool_ = tool_.to_dict()
            self.tools.add(tool_["tool_id"])
            if "commit-scribe" in tool_["tool_id"]:
                self.tool_commit_scribe = tool_["tool_id"]
            elif "log-detective" in tool_["tool_id"]:
                self.tool_log_detective = tool_["tool_id"]
            elif "schema-forge" in tool_["tool_id"]:
                self.tool_schema_forge = tool_["tool_id"]

        # Initialize HIS Client
        his_config = getattr(self.subject.persona, 'config', {}).get("parameters", {}).get("HIS_CONFIG", {}) if hasattr(self.subject, 'persona') else {}
        self.his_client = None
        if his_config:
            self.his_client = HisClient(
                base_url=his_config.get("HIS_BASE_URL", "http://localhost"),
                poll_interval=his_config.get("HIS_POLL_INTERVAL", 1.0),
                max_wait=his_config.get("HIS_MAX_WAIT", 60)
            )

        self.metrics.set_agent_identity(subject_id=subject_id) #send any kwargs to set the identity properties
        self.metrics.set_agent_state("ready")

    def _log_to_his(self, target_id, job_data):
        try:
            source_id = getattr(self.subject.identity, 'subject_id', 'unknown')
            target_id_mapped = {v: k for k, v in NODE_ID_MAPPING.items()}.get(target_id, target_id)
            msg = {"text": str(job_data), "source_id": source_id, "destination_id": target_id_mapped, "team": "Review Team", "timestamp": time.time()}
            if self.his_client:
                self.his_client.submit(input_data=msg)
        except Exception:
            pass

    def get_muxer(self):
        return None

    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        start_time = time.perf_counter()
        _tracer = self.metrics.get_tracer()
        user_task_id = task.job_data.get("user_task_id") or task.task_id

        self.metrics.record_task_mapping(user_task_id=user_task_id, task_id=task.task_id)
        subject_id = getattr(self.subject.identity, 'subject_id', 'unknown')

        with _tracer.span(user_task_id, subject_id) as agent_span:
            with _tracer.span(task.task_id, "on_preprocess", parent_span_id=agent_span.span_id) as span:
                try:
                    log.info(f"Preprocessing task {task.task_id} {task.job_data}")
                    job = task.job_data
                    
                    # Check for required fields (code, final_project_outcome, or user_request)
                    if not job.get("user_request"):
                        log.warning("Task %s missing user_request required keys in job_data — skipping.", task.task_id)
                        self.metrics.increment_preprocess_skipped(reason="missing_required_keys", user_task_id=user_task_id, task_id=task.task_id)
                        duration = time.perf_counter() - start_time
                        self.metrics.observe_histogram_preprocess(duration=duration, action="skipped", exception="", user_task_id=user_task_id, task_id=task.task_id)
                        log.info(f"Early Exit: Preprocess finished. action=skipped duration_seconds={duration:.6f}")
                        return None
                    
                    # Success path
                    self.metrics.increment_preprocess_total(user_task_id=user_task_id, task_id=task.task_id)
                    duration = time.perf_counter() - start_time
                    self.metrics.observe_histogram_preprocess(duration=duration, action="success", exception="", user_task_id=user_task_id, task_id=task.task_id)
                    log.info(f"Success: Preprocess finished. action=success duration_seconds={duration:.6f}")
                    return [task]

                except Exception as e:
                    duration = time.perf_counter() - start_time
                    exception_name = type(e).__name__ #(e.g., KeyError, ValueError, ConnectionError)
                    
                    # Track the error in Prometheus
                    self.metrics.increment_preprocess_errors(exception=exception_name, user_task_id=user_task_id, task_id=task.task_id)
                    self.metrics.observe_histogram_preprocess(duration=duration, action="failed", exception=exception_name, user_task_id=user_task_id, task_id=task.task_id)
                    
                    # Mark the trace span as failed and attach the stack trace
                    if hasattr(span, "record_exception"):  # OpenTelemetry style
                        span.record_exception(e) #Instead of just knowing that it failed, the trace will now embed the exact Python traceback inside the timeline. You won't even need to open your centralized logging system to see what line blew up.
                        span.set_status("ERROR", str(e)) #This flags the specific span in your tracing UI as a failure. It usually turns the bar bright red, making it instantly visible when hunting for bad requests.
                    elif hasattr(span, "set_tag"):         # Jaeger/OpenTracing style
                        span.set_tag("error", True)
                        span.log_kv({"event": "error", "error.object": e, "message": str(e)})
                    
                    log.info(f"Failure: Preprocess finished. action=failed exception={exception_name} duration_seconds={duration:.6f}")
                    raise

    def on_data(self, task: AgentTask) -> AgentResult:
        self.metrics.increase_ondata_active_tasks()
        self.metrics.set_agent_state("processing")
        status = "ok"
        t0 = time.perf_counter()
        _tracer = self.metrics.get_tracer()
        exception_name = ""
        action = "success"
        user_task_id = task.job_data.get("user_task_id") or task.task_id

        subject_id = getattr(self.subject.identity, 'subject_id', 'unknown')

        with _tracer.span(user_task_id, subject_id) as agent_span:
            with _tracer.span(task.task_id, "on_data", parent_span_id=agent_span.span_id) as root_span:
                try:
                    job = task.job_data
                    # Log incoming request
                    self._log_to_his(
                        target_id=NODE_TOOL_DEMO, # Self is target of incoming
                        job_data={"task_type": "INCOMING_TASK", "payload": job}
                    )

                    provider_name = self.llm_block_id
                    if "openai:" in self.llm_block_id:
                        provider_name = self.llm_block_id.replace("openai:", "")
                    elif "gemini:" in self.llm_block_id:
                        provider_name = self.llm_block_id.replace("gemini:", "")

                    # Sending very generic prompt to LLM to choose an tool based in input_dict
                    prompt="What tools can be used to analyse this data"
                    input_dict={
                            "input": job,
                            "tool_model": copy.deepcopy(self.selected_tool_model)
                        }
                    response = self._call_tool_using_search_and_execute_tool(
                        user_task_id=user_task_id,
                        task_id=task.task_id, 
                        parent_span_id=root_span.span_id, 
                        prompt=prompt, 
                        input_data=input_dict,
                        provider=provider_name
                    )
                    print(response)

                    # other functions in self.tools are as below
                    # 1. For Tool Search: 
                    # tool_id = tools.search_tool(
                    #     "Analyse application logs and identify the root cause of the failure"
                    # )
                    # response = self._search_tool_using_tool_search_api(
                    #     user_task_id=user_task_id,
                    #     task_id=task.task_id, 
                    #     parent_span_id=root_span.span_id, 
                    #     prompt=prompt, 
                    #     provider=provider_name
                    # )

                    # 2. For Tool Execute by ID
                    # response = self._call_tool_using_execute_tool_by_id(
                    #     user_task_id=user_task_id,
                    #     task_id=task.task_id, 
                    #     parent_span_id=root_span.span_id, 
                    #     tool_id="agentspace.commit-scribe.v4",
                    #     input_data=input_dict
                    # )
                        
                    job_output = response
                    if isinstance(job_output, dict):
                        job_output["user_task_id"] = user_task_id

                    # Log outgoing result
                    self._log_to_his(
                        target_id="USER", # Terminal node
                        job_data={"task_type": "OUTGOING_RESULT", "payload": job_output}
                    )

                    return AgentResult(
                        task_id=task.task_id,
                        job_output=job_output,
                        job_output_metadata={},
                        is_error=False,
                    )

                except Exception as e:
                    log.exception("Task %s — unexpected error in on_data: %s", task.task_id, e)
                    action = "failed"
                    exception_name = type(e).__name__ #(e.g., KeyError, ValueError, ConnectionError)
                    # Mark the trace span as failed and attach the stack trace
                    if hasattr(root_span, "record_exception"):  # OpenTelemetry style
                        root_span.record_exception(e) #Instead of just knowing that it failed, the trace will now embed the exact Python traceback inside the timeline. You won't even need to open your centralized logging system to see what line blew up.
                        root_span.set_status("ERROR", str(e)) #This flags the specific span in your tracing UI as a failure. It usually turns the bar bright red, making it instantly visible when hunting for bad requests.
                    elif hasattr(root_span, "set_tag"):         # Jaeger/OpenTracing style
                        root_span.set_tag("error", True)
                        root_span.log_kv({"event": "error", "error.object": e, "message": str(e)})

                    return AgentResult(
                        task_id=task.task_id,
                        is_error=True,
                        error_data={"stage": "on_data", "message": str(e)},
                    )
                finally:
                    self.metrics.decrease_ondata_active_tasks()
                    self.metrics.increase_tasks_total(status=action, user_task_id=user_task_id, task_id=task.task_id)
                    self.metrics.set_agent_state("ready")
                    elapsed = time.perf_counter() - t0
                    self.metrics.observe_histogram_ondata(duration=elapsed, action=action, exception=exception_name, user_task_id=user_task_id, task_id=task.task_id)
                    log.info(f"on_data finished. action={action} exception={exception_name} duration_seconds={elapsed:.6f}")

    def _call_tool_using_search_and_execute_tool(self, user_task_id: str, task_id: str, parent_span_id: str, prompt: str, input_data: dict, provider: str) -> dict:
        """Call an agent function, recording duration and status as metrics and a child trace span."""
        log.info("Calling %s", "search_and_execute_tool")
        fn_status = "success"
        t0 = time.perf_counter()
        _tracer = self.metrics.get_tracer()

        # Inject user_task_id and task_id to input_data for propagation
        input_data.setdefault("user_task_id", user_task_id)
        input_data.setdefault("task_id", task_id)

        with _tracer.span(task_id, "search_and_execute_tool", parent_span_id=parent_span_id):
            try:
                response = self.tools.search_and_execute_tool(
                    prompt=prompt,
                    input_dict=input_data,
                    provider=provider
                )
                print(response)

                if isinstance(response, dict) and "error" in response:
                    raise Exception(f"search_and_execute_tool failed: {response['error']}")                
                return response
            except Exception as e:
                fn_status = "failed"
                exception_name = type(e).__name__ #(e.g., KeyError, ValueError, ConnectionError)
                self.metrics.increase_tool_error_total(tool_id="search_and_execute_tool", exception=exception_name, user_task_id=user_task_id, task_id=task_id)
                raise
            finally:
                elapsed = time.perf_counter() - t0
                self.metrics.observe_histogram_toolcall_duration(
                    tool_id="search_and_execute_tool", duration=elapsed,
                    status=fn_status, user_task_id=user_task_id, task_id=task_id
                )
                self.metrics.increase_toolcall_total(tool_id="search_and_execute_tool", status=fn_status, user_task_id=user_task_id, task_id=task_id)

    def _search_tool_using_tool_search_api(self, user_task_id: str, task_id: str, parent_span_id: str, prompt: str, provider: str) -> dict:
        """Call an agent function, recording duration and status as metrics and a child trace span."""
        log.info("Calling %s", "tool_search_api")
        fn_status = "success"
        t0 = time.perf_counter()
        _tracer = self.metrics.get_tracer()

        with _tracer.span(task_id, "tool_search_api", parent_span_id=parent_span_id):
            try:
                response = self.tools.search_tool(
                    prompt=prompt,
                    provider=provider
                )
                print(response)

                if isinstance(response, dict) and "error" in response:
                    raise Exception(f"tool_search_api failed: {response['error']}")                
                return response
            except Exception as e:
                fn_status = "failed"
                exception_name = type(e).__name__ #(e.g., KeyError, ValueError, ConnectionError)
                self.metrics.increase_tool_error_total(tool_id="tool_search_api", exception=exception_name, user_task_id=user_task_id, task_id=task_id)
                raise
            finally:
                elapsed = time.perf_counter() - t0
                self.metrics.observe_histogram_toolcall_duration(
                    tool_id="tool_search_api", duration=elapsed,
                    status=fn_status, user_task_id=user_task_id, task_id=task_id
                )
                self.metrics.increase_toolcall_total(tool_id="tool_search_api", status=fn_status, user_task_id=user_task_id, task_id=task_id)

    def _call_tool_using_execute_tool_by_id(self, user_task_id: str, task_id: str, parent_span_id: str, tool_id: str, input_data: dict) -> dict:
        """Call an agent function, recording duration and status as metrics and a child trace span."""
        log.info("Calling %s", tool_id)
        fn_status = "success"
        t0 = time.perf_counter()
        _tracer = self.metrics.get_tracer()

        # Inject user_task_id and task_id to input_data for propagation
        input_data.setdefault("user_task_id", user_task_id)
        input_data.setdefault("task_id", task_id)

        with _tracer.span(task_id, tool_id, parent_span_id=parent_span_id):
            try:
                response = self.tools.execute_tool_by_id(tool_id=tool_id, input_data=input_data)
                print(response)

                if isinstance(response, dict) and "error" in response:
                    raise Exception(f"{tool_id} failed: {response['error']}")                
                return response
            except Exception as e:
                fn_status = "failed"
                exception_name = type(e).__name__ #(e.g., KeyError, ValueError, ConnectionError)
                self.metrics.increase_tool_error_total(tool_id=tool_id, exception=exception_name, user_task_id=user_task_id, task_id=task_id)
                raise
            finally:
                elapsed = time.perf_counter() - t0
                self.metrics.observe_histogram_toolcall_duration(
                    tool_id=tool_id, duration=elapsed,
                    status=fn_status, user_task_id=user_task_id, task_id=task_id
                )
                self.metrics.increase_toolcall_total(tool_id=tool_id, status=fn_status, user_task_id=user_task_id, task_id=task_id)
            

if __name__ == "__main__":
    main(ToolUsageDemoAgent)
