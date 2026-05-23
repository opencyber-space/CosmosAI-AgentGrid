import logging
import uuid
import yaml
import json
import dspy
import copy
from typing import List, Optional

from agents_sdk.core.agent_executor import AgentTask, AgentResult, Context
from agents_sdk.core.main import main
from agents_sdk.core.known_agents import KnownAgents
from agents_search.search import AgentSearchSelector
from utils.dspy_aios_llms import AIOS_DSPy_LMs
from utils.help_desk_pydatic_models import validate_helpdesk_llm_output, SynthesizerOutput

log = logging.getLogger(__name__)

class Muxer:
    """
    Collects multiple packets for a session and returns a single task with all aggregated data.
    """
    def __init__(self, N) -> None:
        self.packets = {} # session_id -> accumulated_data
        self.expected_counts = {} # session_id -> expected number of packets
        self.received_counts = {} # session_id -> current count

    def add(self, key, task: AgentTask):
        log.info(f"[Muxer] Adding task for key {key}. Job data keys: {list(task.job_data.keys())}")
        
        session_id = key
        if session_id not in self.packets:
            self.packets[session_id] = {}
            self.received_counts[session_id] = 0
            self.expected_counts[session_id] = 1 # Default

        # 1. Update accumulated data
        exclude_keys = {"mux_size", "model_name", "communication_type", "session_id"}
        for k, v in task.job_data.items():
            if k not in exclude_keys:
                self.packets[session_id][k] = v

        # 2. Handle 'mux_size' packet (control packet from router)
        if "mux_size" in task.job_data:
            self.expected_counts[session_id] = task.job_data["mux_size"]
            log.info(f"[Muxer] Set expected mux_size for {session_id} to {self.expected_counts[session_id]}")
        else:
            # Result packet from a specialized agent
            self.received_counts[session_id] += 1

        log.info(f"[Muxer] Session {session_id}: Received {self.received_counts[session_id]}/{self.expected_counts[session_id]}")

        # 3. Check if we have all packets
        if self.received_counts[session_id] >= self.expected_counts[session_id]:
            log.info(f"[Muxer] All packets received for {session_id}. Releasing aggregated task.")
            aggregated_task = copy.deepcopy(task)
            aggregated_task.job_data = self.packets[session_id]
            # Clean up
            del self.packets[session_id]
            del self.expected_counts[session_id]
            del self.received_counts[session_id]
            return aggregated_task
        
        return None

# --- DSPy Signatures ---
class SynthesizerSignature(dspy.Signature):
    """
    You are HELP-DESK synthesizer-agent. Input: a JSON object containing the outputs from all specialized helpdesk agents (Account, Billing, CX, Compliance, Security, Tech) along with the "original_user_request" and "router_output". Your job is to: 1. Aggregate findings from each expert agent. 2. Resolve any contradictions between agent recommendations. 3. Formulate a single, cohesive, and empathetic final response for the user. 4. Return ONLY valid JSON that conforms to the Pydantic model SynthesizerOutput with this schema: {"domain":"synthesizer","final_response":string,"internal_summary":string,"action_items":[{"who":string,"action":string,"priority":string}],"overall_sentiment":number,"further_action_required":boolean}. Ensure the final_response is helpful, clear, and directly addresses the user's original request based on the collective intelligence of the agent group. Return ONLY JSON matching SynthesizerOutput exactly.
    """
    aggregated_data = dspy.InputField(desc="Aggregated JSON data from all helpdesk agents and router")
    synthesized_output = dspy.OutputField(desc="JSON matching SynthesizerOutput schema")

class SynthesizerModule(dspy.Module):
    def __init__(self, system_prompt):
        super().__init__()
        self.synthesizer = dspy.ChainOfThought(SynthesizerSignature.with_instructions(system_prompt))

    def forward(self, aggregated_data):
        return self.synthesizer(aggregated_data=aggregated_data)

class AgentPayloadProcessor:
    def prepare_payload(self, task: AgentTask):
        data = task.job_data
        model_name = data.get("model_name", "aios:qwen3-1-7b-vllm-block")
        session_id = data.get("session_id", str(uuid.uuid4()))
        return model_name, session_id

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

        # Load agents config
        try:
            with open("agents_config.yaml", "r") as f:
                self.agents_config = yaml.safe_load(f)
        except Exception as e:
            log.error(f"Failed to load agents_config.yaml: {e}")
            self.agents_config = {}

        # Initialize Muxer
        mux_size = 1
        try:
            mux_size = self.subject.persona.config["parameters"].get("mux_size", 1)
        except:
            pass
        self.muxer = Muxer(N=mux_size)

        # Initialize DSPy helpers
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        self.module = SynthesizerModule(self.persona_default_system_message)
        self.payload_processor = AgentPayloadProcessor()
        self.model_context = ModelContextManager(self.aios_dspy_lm)

    def get_muxer(self):
        return self.muxer

    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        log.info(f"Preprocessing task {task.task_id} {task.job_data}")
        session_id = task.job_data.get("session_id")
        if not session_id:
            log.warning(f"Task {task.task_id} has no session_id, passing through.")
            return [task]
        
        aggregated_task = self.muxer.add(session_id, task)
        if aggregated_task:
            return [aggregated_task]
        return None

    def _prepare_inputs(self, task: AgentTask):
        return self.payload_processor.prepare_payload(task)

    def _execute_worker(self, aggregated_data, model_name, session_id):
        log.info(f"[synthesizer-agent] Synthesizing results. Aggregated keys: {list(aggregated_data.keys())}")
        
        llm_session_id = str(uuid.uuid4())
        with self.model_context.get_context(model_name=model_name, session_id=llm_session_id):
            result = self.module.forward(aggregated_data=json.dumps(aggregated_data))
        
        out_synthesized = result.synthesized_output
        if isinstance(out_synthesized, str):
            try:
                out_synthesized = json.loads(out_synthesized)
            except:
                pass
        return out_synthesized

    def on_data(self, task: AgentTask) -> AgentResult:
        try:
            model_name, session_id = self._prepare_inputs(task)
            aggregated_data = task.job_data

            # 1. Run worker
            out_synthesized = self._execute_worker(aggregated_data, model_name, session_id)
            log.info(f"Synthesizer Result: {out_synthesized}")

            # 2. Return the final result
            return AgentResult(
                task_id=task.task_id,
                job_output={"text": json.dumps(out_synthesized)},
                job_output_metadata={"length": len(json.dumps(out_synthesized))},
                is_error=False
            )

        except Exception as e:
            log.exception(f"Error in Synthesizer Agent: {e}")
            return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})

if __name__ == "__main__":
    main(SampleAgent)
