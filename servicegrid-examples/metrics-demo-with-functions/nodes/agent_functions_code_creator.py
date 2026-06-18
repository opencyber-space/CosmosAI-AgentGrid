import time
import logging
import uuid
import json
import dspy
from typing import List, Optional

from agents_sdk.core.agent_executor import AgentResult, AgentTask, Context
from agents_sdk.core.main import main
from agents_sdk.core.his import HisClient
from utils.dspy_aios_llms import AIOS_DSPy_LMs
from utils.json_utils import extract_json
from utils.metrics_util import AgentMetrics

log = logging.getLogger(__name__)

NODE_ID_MAPPING = {
    "agent-code-creator-metrics-in-functions": "my-behavioral-code-creator",
    "agent-code-reviewer-metrics-in-functions": "my-behavioral-reviewer",
}

NODE_CODE_CREATOR = "my-behavioral-code-creator"
NODE_REVIEWER = "my-behavioral-reviewer"


# --- 1. The Signatures ---

class CodeCreatorSignature(dspy.Signature):
    """
    ### ROLE
    You are an expert software developer.

    ### TASK
    You will be given a user request to generate a python function.
    Your task is to generate ONE python function that takes arguments named arg1, arg2, etc. as needed.
    You must output the code, the function_name, and a brief description.

    ### RULES
    Respond ONLY with a valid JSON object, no preamble, no markdown:
    {
      "code": "def add(arg1, arg2):\n    return arg1 + arg2",
      "function_name": "add",
      "description": "Adds two numbers and returns the result"
    }
    """
    user_request = dspy.InputField(desc="The user request for generating code")
    code_generation = dspy.OutputField(desc="Structured JSON with code, function_name, and description")

class CodeCreatorModule(dspy.Module):
    def __init__(self, system_prompt):
        super().__init__()
        self.generator = dspy.ChainOfThought(CodeCreatorSignature)

    def forward(self, user_request):
        return self.generator(user_request=user_request)

# --- 2. Helper Classes ---

class AgentPayloadProcessor:
    def prepare_payload(self, task: AgentTask):
        data = task.job_data
        user_request = data.get("user_request", "Create a basic function.")
        user_task_id = data.get("user_task_id", task.task_id)

        user_message = (
            "Generate a python function based on this request:\n\n"
            + user_request
        )
        communication_type = data.get("communication_type", "delegate")
        model_name = data.get("model_name", "aios:qwen3-1-7b-vllm-block")
        session_id = data.get("session_id", str(uuid.uuid4()))
        return user_message, communication_type, model_name, session_id, user_task_id

class ModelContextManager:
    def __init__(self, aios_dspy_lm: AIOS_DSPy_LMs):
        self.aios_dspy_lm = aios_dspy_lm

    def get_context(self, model_name: str, session_id: str):
        return dspy.settings.context(
            lm=self.aios_dspy_lm.get_choosen_model(
                model_name=model_name,
                session_id=session_id
            )
        )

# --- 3. The Code Creator Agent ---

class CodeCreatorAgent:
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

        self.persona_default_system_message = getattr(self.subject.persona, 'default_system_message', "") if hasattr(self.subject, 'persona') else ""
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        self.module = CodeCreatorModule(self.persona_default_system_message)
        self.payload_processor = AgentPayloadProcessor()
        self.model_context = ModelContextManager(self.aios_dspy_lm)
        self.task_registry = {}
        
        # Initialize HIS Client
        his_config = getattr(self.subject.persona, 'config', {}).get("parameters", {}).get("HIS_CONFIG", {}) if hasattr(self.subject, 'persona') else {}
        self.his_client = HisClient(
            base_url=his_config.get("HIS_BASE_URL", "http://localhost"),
            poll_interval=his_config.get("HIS_POLL_INTERVAL", 1.0),
            max_wait=his_config.get("HIS_MAX_WAIT", 60)
        )

        self.metrics.set_agent_identity(subject_id=subject_id)
        self.metrics.set_agent_state("ready")

    def _execute_worker(self, user_request, model_name, session_id):
        with self.model_context.get_context(model_name=model_name, session_id=session_id):
            return self.module.forward(user_request=user_request)

    def _log_to_his(self, target_id, job_data):
        try:
            source_id = getattr(self.subject.identity, 'subject_id', 'unknown')
            target_id_mapped = {v: k for k, v in NODE_ID_MAPPING.items()}.get(target_id, target_id)
            msg = {"text": str(job_data), "source_id": source_id, "destination_id": target_id_mapped, "team": "Dev Team", "timestamp": time.time()}
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
                    # Check for required fields (code, final_project_outcome, or user_request)
                    job = task.job_data
                    if not job.get("user_request"):
                        log.warning("Task %s missing 'user_request' in job_data — skipping.", task.task_id)
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
                    data = task.job_data
                    if "final_project_outcome" in data:
                        log.info(f"Received Final Project Outcome! Task {task.task_id} successfully completed.")
                        return AgentResult(task_id=task.task_id, is_error=False, job_output=data, job_output_metadata={})
                    
                    user_message, communication_type, model_name, session_id, user_task_id = self.payload_processor.prepare_payload(task)

                    self.task_registry[task.task_id] = {
                        "user_request": user_message,
                        "model_name": model_name,
                        "session_id": session_id,
                        "user_task_id": user_task_id
                    }
                    
                    # Log incoming request
                    self._log_to_his(
                        target_id=NODE_CODE_CREATOR, # Self is target of incoming
                        job_data={"task_type": "INCOMING_TASK", "payload": data}
                    )
                    
                    log.info(f"Generating code based on user request")
                    
                    llm_session_id = str(uuid.uuid4())
                    result = self._execute_worker(user_message, model_name, llm_session_id)
                    log.info(f"Code generation result: {result}")
                    
                    parsed = extract_json(result.code_generation)
                    if not parsed and isinstance(result.code_generation, str):
                        try:
                            import ast
                            parsed = ast.literal_eval(result.code_generation)
                        except:
                            pass
                    if not isinstance(parsed, dict):
                        parsed = {}
                        
                    code = parsed.get("code", "")
                    function_name = parsed.get("function_name", "")
                    description = parsed.get("description", "")

                    job_output = {
                        "user_request": task.job_data.get("user_request", ""),
                        "user_task_id": user_task_id,
                        "code": code,
                        "function_name": function_name,
                        "description": description
                    }
                    
                    # Log outgoing result
                    self._log_to_his(
                        target_id=NODE_REVIEWER, # Send to next agent
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

if __name__ == "__main__":
    main(CodeCreatorAgent)

