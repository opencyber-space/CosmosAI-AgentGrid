import logging
import uuid
import json
import time
import dspy
from typing import List, Optional

from agents_sdk.core.agent_executor import AgentResult, AgentTask, Context
from agents_sdk.core.main import main
from agents_sdk.core.his import HisClient
from utils.dspy_aios_llms import AIOS_DSPy_LMs
from utils.hierarchical_agents_models import ProblemStatement
from utils.json_utils import extract_json

log = logging.getLogger(__name__)

NODE_ID_MAPPING = {
    "agent-workflow-ceo": "my-ceo-agent",
    "agent-workflow-cos": "my-chief-of-staff-agent"
}

# --- 1. The Signatures ---

class CEOSignature(dspy.Signature):
    """
    ### ROLE
    You are the CEO (Vision Owner) of a software company.

    ### TASK
    Refine the USER's raw software idea into a structured Problem Statement.
    Identify the core product idea and the desired priority (cheap, fast, or premium).

    ### RULES
    1. Focus on the vision and business value.
    2. Be decisive but clear.
    3. Output EXACTLY a JSON block matching the ProblemStatement schema.
    """
    raw_idea = dspy.InputField(desc="The raw software idea from the USER")
    problem_statement = dspy.OutputField(desc="Structured JSON matching ProblemStatement: {product_idea: str, priority: 'cheap'|'fast'|'premium'}")

class CEOModule(dspy.Module):
    def __init__(self, system_prompt):
        super().__init__()
        self.refiner = dspy.ChainOfThought(CEOSignature)

    def forward(self, raw_idea):
        return self.refiner(raw_idea=raw_idea)

# --- 2. Helper Classes ---

class AgentPayloadProcessor:
    def prepare_payload(self, task: AgentTask):
        data = task.job_data
        if not isinstance(data, dict):
            data = {}
        if "initial_input" in data and isinstance(data["initial_input"], dict):
            data = data["initial_input"]
        raw_idea = data.get("text") or data.get("user_request") or ""
        communication_type = data.get("communication_type", "delegate")
        model_name = data.get("model_name", "aios:qwen3-1-7b-vllm-block")
        session_id = data.get("session_id", str(uuid.uuid4()))
        return raw_idea, communication_type, model_name, session_id

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

# --- 3. The CEO Agent ---

class CEOAgent:
    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        self.persona_default_system_message = getattr(self.subject.persona, 'default_system_message', "") if hasattr(self.subject, 'persona') else ""
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        self.module = CEOModule(self.persona_default_system_message)
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

    def _execute_worker(self, raw_idea, model_name, session_id):
        with self.model_context.get_context(model_name=model_name, session_id=session_id):
            return self.module.forward(raw_idea=raw_idea)

    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        log.info(f"Preprocessing task {task.task_id} {task.job_data}")
        data = task.job_data
        if not isinstance(data, dict):
            data = {}
        if "initial_input" in data and isinstance(data["initial_input"], dict):
            data = data["initial_input"]
            
        text = data.get("text") or data.get("user_request")
        if not text and "final_project_outcome" not in data and "final_project_outcome" not in (task.job_data if isinstance(task.job_data, dict) else {}):
            log.warning("Task %s has no 'text', 'user_request', or 'final_project_outcome' in job_data, skipping.", task.task_id)
            return None
        return [task]

    def _log_to_his(self, target_id, job_data):
        try:
            source_id = getattr(self.subject.identity, 'subject_id', 'unknown')
            target_id_mapped = {v: k for k, v in NODE_ID_MAPPING.items()}.get(target_id, target_id)
            msg = {"text": str(job_data), "source_id": source_id, "destination_id": target_id_mapped, "team": "CEO Team", "timestamp": time.time()}
            self.his_client.submit(input_data=msg)
        except Exception:
            pass

    def get_muxer(self):
        return None

    def on_data(self, task: AgentTask) -> AgentResult:
        try:
            data = task.job_data
            if not isinstance(data, dict):
                data = {}
            
            if "final_project_outcome" in data:
                log.info(f"CEO Received Final Project Outcome! Task {task.task_id} successfully completed.")
                return AgentResult(task_id=task.task_id, is_error=False, job_output=data)
                
            if "initial_input" in data and isinstance(data["initial_input"], dict):
                log.info("Unpacking dynamic router payload in CEO Agent")
                inner = data.get("initial_input", {})
                if "final_project_outcome" in inner:
                    log.info(f"CEO Received Final Project Outcome in initial_input! Task {task.task_id} successfully completed.")
                    return AgentResult(task_id=task.task_id, is_error=False, job_output=data)
                data = inner
            
            raw_idea, communication_type, model_name, session_id = self.payload_processor.prepare_payload(task)
            log.info(f"CEO received raw idea: {raw_idea}")

            # Store in registry
            self.task_registry[task.task_id] = {
                "user_request": raw_idea,
                "model_name": model_name,
                "session_id": session_id
            }

            # 1. Refine the idea using LLM
            llm_session_id = str(uuid.uuid4())
            result = self._execute_worker(raw_idea, model_name, llm_session_id)
            log.info(f"CEO refinement result: {result}")

            # 2. Parse problem statement
            ps_raw = result.problem_statement
            ps_data = extract_json(ps_raw)
            problem_statement = ProblemStatement(**ps_data)

            # 3. Format dynamic job output to trigger CoS node in workflow graph
            cos_agent_id = "my-chief-of-staff-agent"
            job_data = {
                "task_type": "initiate",
                "text": json.dumps(problem_statement.dict()),
                "problem_statement": problem_statement.dict(),
                "user_request": raw_idea,
                "task_id": task.task_id,
                "session_id": session_id,
                "model_name": model_name,
                "communication_type": communication_type
            }

            self._log_to_his(cos_agent_id, job_data)
            return AgentResult(task_id=task.task_id, job_output=job_data, job_output_metadata={"next_nodes":[cos_agent_id]}, is_error=False)

        except Exception as e:
            log.exception(f"Error in CEO Agent: {e}")
            return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})

if __name__ == "__main__":
    main(CEOAgent)
