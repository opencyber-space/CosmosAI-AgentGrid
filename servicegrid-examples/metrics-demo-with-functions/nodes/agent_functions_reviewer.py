import time
import logging
from typing import List, Optional

from agents_sdk.core.agent_executor import AgentResult, AgentTask, Context
from agents_sdk.core.main import main
from agents_sdk.core.his import HisClient
from agents_functions import AgentFunctions
from utils.metrics_util import AgentMetrics

log = logging.getLogger(__name__)

NODE_ID_MAPPING = {
    "agent-code-creator-metrics-in-functions": "my-behavioral-code-creator",
    "agent-code-reviewer-metrics-in-functions": "my-behavioral-reviewer",
}

NODE_CODE_CREATOR = "my-behavioral-code-creator"
NODE_REVIEWER = "my-behavioral-reviewer"

class BehavioralReviewerAgent:
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
        functions_config = config_params.get("FUNCTIONS_CONFIG", {})

        self.llm_block_id = functions_config.get("llm_block_id")

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
        
        functions_registry_url = functions_config.get("functions_registry_url")
        unique_parameter = functions_config.get("unique_parameter")
        executor_id = functions_config.get("executor_id")
        num_workers = functions_config.get("num_workers")
        
        self.agent_function = AgentFunctions(
            functions_registry_url=functions_registry_url,
            unique_parameter=unique_parameter,
            executor_id=executor_id,
            num_workers=int(num_workers)
        )

        subject_functions = getattr(integrations, 'subject_functions', []) if integrations else []
        self.code_validator = ""
        self.test_generator = ""
        self.test_runner = ""
        self.code_validator_params = {}
        self.test_generator_params = {}
        self.test_runner_params = {}
        for function_ in subject_functions:
            if type(function_) != dict:
                function_ = function_.to_dict()
            self.agent_function.add(function_["function_id"])
            if "code-validator" in function_["function_id"]:
                self.code_validator = function_["function_id"]
                self.code_validator_params = function_["function_custom_parameters"]
            elif "test-generator" in function_["function_id"]:
                self.test_generator = function_["function_id"]
                self.test_generator_params = function_["function_custom_parameters"]
            elif "test-runner" in function_["function_id"]:
                self.test_runner = function_["function_id"]
                self.test_runner_params = function_["function_custom_parameters"]

        if not self.code_validator or not self.test_generator or not self.test_runner:
            raise ValueError("Code validator, test generator, or test runner not found")
        
        # Initialize HIS Client
        his_config = getattr(self.subject.persona, 'config', {}).get("parameters", {}).get("HIS_CONFIG", {}) if hasattr(self.subject, 'persona') else {}
        self.his_client = HisClient(
            base_url=his_config.get("HIS_BASE_URL", "http://localhost"),
            poll_interval=his_config.get("HIS_POLL_INTERVAL", 1.0),
            max_wait=his_config.get("HIS_MAX_WAIT", 60)
        )

        self.metrics.set_agent_identity(subject_id=subject_id)
        self.metrics.set_agent_state("ready")

    def _log_to_his(self, target_id, job_data):
        try:
            source_id = getattr(self.subject.identity, 'subject_id', 'unknown')
            target_id_mapped = {v: k for k, v in NODE_ID_MAPPING.items()}.get(target_id, target_id)
            msg = {"text": str(job_data), "source_id": source_id, "destination_id": target_id_mapped, "team": "Review Team", "timestamp": time.time()}
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
                    if not job.get("code"):
                        log.warning("Task %s missing 'code' in job_data — skipping.", task.task_id)
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
                    exception_name = type(e).__name__
                    
                    # Track the error in Prometheus
                    self.metrics.increment_preprocess_errors(exception=exception_name, user_task_id=user_task_id, task_id=task.task_id)
                    self.metrics.observe_histogram_preprocess(duration=duration, action="failed", exception=exception_name, user_task_id=user_task_id, task_id=task.task_id)
                    
                    # Mark the trace span as failed and attach the stack trace
                    if hasattr(span, "record_exception"):  # OpenTelemetry style
                        span.record_exception(e)
                        span.set_status("ERROR", str(e))
                    elif hasattr(span, "set_tag"):         # Jaeger/OpenTracing style
                        span.set_tag("error", True)
                        span.log_kv({"event": "error", "error.object": e, "message": str(e)})
                
                    log.info(f"Failure: Preprocess finished. action=failed exception={exception_name} duration_seconds={duration:.6f}")
                    raise

    def on_data(self, task: AgentTask) -> AgentResult:
        self.metrics.increase_ondata_active_tasks()
        self.metrics.set_agent_state("processing")
        action = "success"
        exception_name = ""
        t0 = time.perf_counter()
        _tracer = self.metrics.get_tracer()
        user_task_id = task.job_data.get("user_task_id") or task.task_id



        subject_id = getattr(self.subject.identity, 'subject_id', 'unknown')

        with _tracer.span(user_task_id, subject_id) as agent_span:
            with _tracer.span(task.task_id, "on_data", parent_span_id=agent_span.span_id) as root_span:
                try:
                    job = task.job_data
                    # Log incoming request
                    self._log_to_his(
                        target_id=NODE_REVIEWER, # Self is target of incoming
                        job_data={"task_type": "INCOMING_TASK", "payload": job}
                    )

                    input_data = {
                        "code": job["code"],
                        "function_name": job.get("function_name", ""),
                        "description": job.get("description", ""),
                    }

                    # Step 1: validate the code
                    result1 = self._call_function(
                        user_task_id=user_task_id,
                        task_id=task.task_id,
                        parent_span_id=root_span.span_id,
                        function_id=self.code_validator,
                        input_data={
                            **input_data
                        },
                        parameters={
                            "tool_model": self.selected_tool_model,
                            **self.code_validator_params
                        }
                    )

                    # Step 2: generate test cases
                    result2 = self._call_function(
                        user_task_id=user_task_id,
                        task_id=task.task_id,
                        parent_span_id=root_span.span_id,
                        function_id=self.test_generator,
                        input_data={
                            **result1
                        },
                        parameters={
                            "tool_model": self.selected_tool_model,
                            **self.test_generator_params
                        }
                    )

                    # Step 3: run the generated tests against the code
                    result3 = self._call_function(
                        user_task_id=user_task_id,
                        task_id=task.task_id,
                        parent_span_id=root_span.span_id,
                        function_id=self.test_runner,
                        input_data={**result2},
                        parameters={
                            **self.test_runner_params
                        }
                    )

                    job_output = result3

                    # Log outgoing result
                    self._log_to_his(
                        target_id="USER", # Terminal node
                        job_data={"task_type": "OUTGOING_RESULT", "payload": job_output}
                    )

                    return AgentResult(
                        task_id=task.task_id,
                        job_output=job_output,
                        job_output_metadata={"functions_called": ["code-validator:1.22.0-stable", "test-generator:1.22.0-stable", "test-runner:1.22.0-stable"]},
                        is_error=False,
                    )

                except Exception as e:
                    log.exception("Task %s — unexpected error in on_data: %s", task.task_id, e)
                    action = "failed"
                    exception_name = type(e).__name__
                    if hasattr(root_span, "record_exception"):
                        root_span.record_exception(e)
                        root_span.set_status("ERROR", str(e))
                    elif hasattr(root_span, "set_tag"):
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

    def _call_function(self, user_task_id: str, task_id: str, parent_span_id: str, function_id: str, input_data: dict, parameters: Optional[dict] = None) -> dict:
        """Call an agent function, recording duration and status as metrics and a child trace span."""
        log.info("Calling %s", function_id)
        fn_status = "success"
        t0 = time.perf_counter()
        _tracer = self.metrics.get_tracer()

        # Inject user_task_id and task_id to parameters for propagation
        params = parameters or {}
        params.setdefault("user_task_id", user_task_id)
        params.setdefault("task_id", task_id)

        with _tracer.span(task_id, function_id, parent_span_id=parent_span_id):
            try:
                response = self.agent_function.call(function_id=function_id, input_data=input_data, parameters=params)
                log.info("%s result: %s", function_id, response)
                
                if isinstance(response, dict) and "error" in response:
                    raise Exception(f"{function_id} failed: {response['error']}")                
                return response
            except Exception as e:
                fn_status = "failed"
                exception_name = type(e).__name__
                self.metrics.increase_function_error_total(function_id=function_id, exception=exception_name, user_task_id=user_task_id, task_id=task_id)
                raise
            finally:
                elapsed = time.perf_counter() - t0
                self.metrics.observe_histogram_function_duration(
                    function_id=function_id, status=fn_status, duration=elapsed, user_task_id=user_task_id, task_id=task_id
                )
                self.metrics.increase_function_calls_total(function_id=function_id, status=fn_status, user_task_id=user_task_id, task_id=task_id)

if __name__ == "__main__":
    main(BehavioralReviewerAgent)
