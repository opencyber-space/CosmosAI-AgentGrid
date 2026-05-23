import logging
import uuid
import json
import dspy
from typing import List, Optional

from agents_sdk.core.agent_executor import AgentResult, AgentTask, Context
from agents_sdk.core.main import main
from agents_sdk.core.his import HisClient
from utils.dspy_aios_llms import AIOS_DSPy_LMs
from utils.hierarchical_agents_models import ProblemStatement
from utils.json_utils import extract_json

log = logging.getLogger(__name__)

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
        # The CEO receives a "go signal" with a software idea
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
        self.persona_default_system_message = self.subject.persona.default_system_message
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        self.module = CEOModule(self.persona_default_system_message)
        self.payload_processor = AgentPayloadProcessor()
        self.model_context = ModelContextManager(self.aios_dspy_lm)
        self.task_registry = {}
        # Initialize HIS Client
        his_config = self.subject.persona.config.get("parameters", {}).get("HIS_CONFIG", {})
        self.his_client = HisClient(
            base_url=his_config["HIS_BASE_URL"],
            poll_interval=his_config.get("HIS_POLL_INTERVAL", 1.0),
            max_wait=his_config.get("HIS_MAX_WAIT", 60)
        )



    def _execute_worker(self, raw_idea, model_name, session_id):
        with self.model_context.get_context(model_name=model_name, session_id=session_id):
            return self.module.forward(raw_idea=raw_idea)


    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        log.info(f"Preprocessing task {task.task_id} {task.job_data}")
        text = task.job_data.get("text")
        if not text and "final_project_outcome" not in task.job_data:
            log.warning("Task %s has no 'text' or 'final_project_outcome' in job_data, skipping.", task.task_id)
            return None
        return [task]
    def _log_to_his(self, target_id, job_data):
        try:
            msg = {"text": str(job_data), "source_id": self.subject.identity.subject_id, "destination_id": target_id, "team": "CEO Team"}
            self.his_client.submit(input_data=msg)
        except Exception:
            pass


    def get_muxer(self):
        return None

    def on_data(self, task: AgentTask) -> AgentResult:
        try:
            data = task.job_data
            if "final_project_outcome" in data:
                log.info(f"CEO Received Final Project Outcome! Task {task.task_id} successfully completed.")
                # We can store this or log it, but we skip further refinement
                return AgentResult(task_id=task.task_id, is_error=False, job_output=data)
            
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

            # 3. Delegate to Chief of Staff
            cos_agent_id = "company-chief-of-staff-agent" # As per hierarchy: CEO -> Chief of Staff
            log.info(f"CEO delegating to {cos_agent_id} via {communication_type}")
            
            job_data = {
                "task_type": "initiate",
                "text": json.dumps(problem_statement.dict()),
                "user_request": raw_idea,
                "task_id": task.task_id,
                "session_id": session_id,
                "model_name": model_name,
                "communication_type": communication_type
            }

            if communication_type == "delegate":
                self._log_to_his(cos_agent_id, job_data)
                self.context.delegator.submit_and_wait(
                    subject_id=cos_agent_id, session_id=session_id,
                    task_id=task.task_id, task_data=job_data
                )
            elif communication_type == "p2p":
                self._log_to_his(cos_agent_id, job_data)
                self.context.p2p_manager.send_sync(
                    task=task, subject_id=cos_agent_id,
                    job_data=job_data,
                    session_id=session_id
                )
            else:
                self._log_to_his(cos_agent_id, job_data)
                self.context.direct.submit(to=cos_agent_id, session_id=session_id, task=task, job_data=job_data)

            return AgentResult(task_id=task.task_id, skip=True)

        except Exception as e:
            log.exception(f"Error in CEO Agent: {e}")
            return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})

if __name__ == "__main__":
    main(CEOAgent)
