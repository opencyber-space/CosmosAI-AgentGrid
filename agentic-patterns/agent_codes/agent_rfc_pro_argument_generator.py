import logging, json, os, dspy, uuid, string, random
from typing import List, Optional
import yaml

from agents_sdk.core.agent_executor import AgentTask, AgentResult
from agents_sdk.core.main import main
from agents_sdk.core.agent_executor import Context

from utils.dspy_aios_llms import AIOS_DSPy_LMs

log = logging.getLogger(__name__)

# --- DSPy Signatures ---
class ProArgumentGeneratorSignature(dspy.Signature):
    """
    You are the pro-argument-generator. Produce high-quality, 'steelman' arguments in favor of the RFC.
    Focus on concrete technical benefits, quantitative improvements (e.g., latency, cost, scalability), 
    and alignment with long-term architectural goals. Avoid generic praise; be specific and technical.
    """
    context_text = dspy.InputField(desc="The RFC context and history")
    pro_arguments = dspy.OutputField(desc="Concise 'pro' arguments")

# --- DSPy Modules ---
class ProArgumentGeneratorModule(dspy.Module):
    def __init__(self, system_prompt):
        super().__init__()
        self.cot = dspy.ChainOfThought(ProArgumentGeneratorSignature.with_instructions(system_prompt))

    def forward(self, context_text):
        return self.cot(context_text=context_text)

class AgentPayloadProcessor:
    def prepare_payload(self, task: AgentTask):
        data = task.job_data
        text = data.get("text", "")
        model_name = data.get("model_name", "aios:qwen3-1-7b-vllm-block")
        session_id = data.get("session_id", str(uuid.uuid4()))
        communication_type = data.get("communication_type", "delegate")
        return text, model_name, session_id, communication_type

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

class SampleAgent:

    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        self.persona_default_system_message = self.subject.persona.default_system_message
        self.aios_dspy_lm = AIOS_DSPy_LMs(self.subject)
        self.module = ProArgumentGeneratorModule(self.persona_default_system_message)
        self.payload_processor = AgentPayloadProcessor()
        self.model_context = ModelContextManager(self.aios_dspy_lm)
        
        # Load agents config
        try:
            with open("agents_config.yaml", "r") as f:
                self.agents_config = yaml.safe_load(f)
        except Exception as e:
            log.error(f"Failed to load agents_config.yaml: {e}")
            self.agents_config = {}

    def get_muxer(self):
        return None

    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        # job_data --> exchange, task --> mesh
        # in exchange, we are positng jobs conceptually
        # in mesh --> we directly submit events
        log.info(f"Preprocessing task {task.task_id} {task.job_data}")
        text = task.job_data.get("text")
        if not text:
            log.warning("Task %s has no 'text' in job_data, skipping.", task.task_id)
            return None
        return [task]

    def _prepare_inputs(self, task: AgentTask):
        return self.payload_processor.prepare_payload(task)

    def _execute_worker(self, text, model_name, session_id):
        with self.model_context.get_context(model_name=model_name, session_id=session_id):
            return self.module(context_text=text)

    def on_data(self, task: AgentTask) -> AgentResult:
        try:
            text, model_name, session_id, communication_type = self._prepare_inputs(task)
            log.info(f"Generating pro-arguments with session_id: {session_id} using model: {model_name}")

            # 1. Run DSPy Module
            llm_session_id = str(uuid.uuid4())
            result = self._execute_worker(text, model_name, llm_session_id)
            
            out_pro = getattr(result, "pro_arguments", "")
            # Encapsulate for synthesizer
            encapsulated_text = (
                f"--- INPUT OF PRO ARGUMENT AGENT ---\n{text}\n\n"
                f"--- OUTPUT OF PRO ARGUMENT AGENT ---\n{out_pro}\n"
            )

            # 2. Determine next agent from config
            next_agent_subject_id = self.agents_config.get("rfc", {}).get(self.subject.identity.subject_id, {}).get("next_agent")
            
            if not next_agent_subject_id or next_agent_subject_id == "false":
                log.info("No next agent configured. Finishing flow.")
                return AgentResult(task_id=task.task_id, job_output={"text": encapsulated_text})

            log.info(f"Preparing to call next agent: {next_agent_subject_id} with communication type: {communication_type}")
            
            next_session_id = str(uuid.uuid4())
            task_data = {
                "text": encapsulated_text,
                "session_id": next_session_id,
                "model_name": model_name,
                "communication_type": communication_type
            }

            if communication_type == "p2p":
                log.info(f"Communicating to {next_agent_subject_id} agent via p2p_manager.")
                self.context.p2p_manager.send_sync(
                    task=task, subject_id=next_agent_subject_id,
                    job_data=task_data, 
                    session_id=next_session_id
                )
            elif communication_type == "direct":
                log.info(f"Communicating to {next_agent_subject_id} agent via direct.")
                self.context.direct.submit(to=next_agent_subject_id, session_id=next_session_id, task=task, job_data=task_data)
            else:
                log.info(f"Communicating to {next_agent_subject_id} agent via fallback.")
                self.context.direct.submit(to=next_agent_subject_id, session_id=next_session_id, task=task, job_data=task_data)

            return AgentResult(
                task_id=task.task_id,
                skip=True
            )

        except Exception as e:
            log.exception(f"Error in Pro Argument Generator Agent: {e}")
            return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})

main(SampleAgent)
