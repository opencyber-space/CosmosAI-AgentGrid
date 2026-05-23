import logging, json, os, dspy, uuid, string, random, copy
from typing import List, Optional
import yaml

from agents_sdk.core.agent_executor import AgentTask, AgentResult
from agents_sdk.core.main import main
from agents_sdk.core.agent_executor import Context

from utils.dspy_aios_llms import AIOS_DSPy_LMs

log = logging.getLogger(__name__)

class Muxer:
    def __init__(self, N) -> None:
        self.packets = {}
        self.N = N

    def add(self, key, task: AgentTask):
        log.info(f"Adding task with key {key} to Muxer.{task}")
        # if key not in self.packets:
        if key not in self.packets:
            self.packets[key] = task
            if self.N==1: #This is for N=1
                return self.packets[key]
        else: # if key in self.packets i.e N>1
            #self.packets[key].append(task)
            if "text" in self.packets[key].job_data: #when text is present
                existing_text = self.packets[key].job_data["text"]
                del self.packets[key].job_data["text"]
                if "text" in task.job_data:
                    self.packets[key].job_data["tasks"] = [existing_text, task.job_data["text"]]
            else:#when text is present i.e N>1 i.e key has happened once before and  initilized tasks
                self.packets[key].job_data.get("tasks").append(task.job_data.get("text",""))
            if len(self.packets[key].job_data.get("tasks")) == self.N:
                log.info(f"Returning muxed task with key {key}")
                returnable = copy.deepcopy(self.packets[key])
                del self.packets[key]
                return returnable
            
        return None

# --- DSPy Signatures ---
class ConsensusSynthesizerSignature(dspy.Signature):
    """
    You are the consensus-synthesizer. Synthesize a balanced recommendation from Pro, Con, and Safeguards inputs.
    Identify the core 'technical tension' or trade-offs. Your output must objectively weigh the benefits 
    against the risks. 
    Structure:
    1. Consensus: Areas of agreement.
    2. Dissent/Trade-offs: Significant risks or unresolved technical debt.
    3. Action Plan: Concrete next steps including must-have safeguards before adoption.
    """
    muxed_context_text = dspy.InputField(desc="The combined context from multiple RFC agents")
    consensus_synthesis = dspy.OutputField(desc="Final consensus, dissent, and action items")

# --- DSPy Modules ---
class ConsensusSynthesizerModule(dspy.Module):
    def __init__(self, system_prompt):
        super().__init__()
        self.cot = dspy.ChainOfThought(ConsensusSynthesizerSignature.with_instructions(system_prompt))

    def forward(self, muxed_context_text):
        return self.cot(muxed_context_text=muxed_context_text)

class AgentPayloadProcessor:
    def prepare_payload(self, task: AgentTask):
        data = task.job_data
        model_name = data.get("model_name", "aios:qwen3-1-7b-vllm-block")
        session_id = data.get("session_id", str(uuid.uuid4()))
        communication_type = data.get("communication_type", "delegate")
        
        if "tasks" in data:
            combined_text = "Consolidated RFC Perspectives:\n\n"
            for t_data in data["tasks"]:
                combined_text += f"{t_data}\n"
            text = combined_text
        else:
            text = data.get("text", "")
            
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
        self.module = ConsensusSynthesizerModule(self.persona_default_system_message)
        self.payload_processor = AgentPayloadProcessor()
        self.model_context = ModelContextManager(self.aios_dspy_lm)
        
        try:
            mux_size = self.subject.persona.config["parameters"].get("mux_size", 1)
            log.info(f"Initializing Muxer with size: {mux_size}")
            self.muxer = Muxer(N=mux_size)
        except Exception as e:
            log.warning(f"Error initializing Muxer, defaulting to 1: {e}")
            self.muxer = Muxer(N=1)

    def get_muxer(self):
        return self.muxer

    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        # job_data --> exchange, task --> mesh
        # in exchange, we are positng jobs conceptually
        # in mesh --> we directly submit events
        log.info(f"Preprocessing task {task.task_id} {task.job_data}")
        if "text" in task.job_data:
            text = task.job_data.get("text")
            if not text:
                log.warning(
                    "Task %s has no 'text' in job_data, skipping.", task.task_id)
                return None
        elif "tasks" in task.job_data:
            return [task]

        return [task]

    def _prepare_inputs(self, task: AgentTask):
        return self.payload_processor.prepare_payload(task)

    def _execute_worker(self, text, model_name, session_id):
        with self.model_context.get_context(model_name=model_name, session_id=session_id):
            return self.module(muxed_context_text=text)

    def on_data(self, task: AgentTask) -> AgentResult:
        try:
            text, model_name, session_id, communication_type = self._prepare_inputs(task)
            log.info(f"Synthesizing consensus with session_id: {session_id}")

            # 1. Run DSPy Module
            llm_session_id = str(uuid.uuid4())
            result = self._execute_worker(text, model_name, llm_session_id)
            
            out = getattr(result, "consensus_synthesis", "")

            return AgentResult(
                task_id=task.task_id,
                job_output={"text": out},
                job_output_metadata={"length": len(out)},
                is_error=False,
            )

        except Exception as e:
            log.exception(f"Error in Consensus Synthesizer Agent: {e}")
            return AgentResult(
                task_id=task.task_id,
                is_error=True,
                error_data={"message": str(e)},
            )

main(SampleAgent)
