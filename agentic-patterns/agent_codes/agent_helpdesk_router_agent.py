import logging
import uuid
import yaml
import json
import dspy
import string
import random
from typing import List, Optional

from agents_sdk.core.agent_executor import AgentTask, AgentResult, Context
from agents_sdk.core.main import main
from agents_sdk.core.known_agents import KnownAgents
from agents_search.search import AgentSearchSelector
from utils.dspy_aios_llms import AIOS_DSPy_LMs
from utils.help_desk_pydatic_models import validate_helpdesk_llm_output, RouterOutput

log = logging.getLogger(__name__)

# --- DSPy Signatures ---
class RouterSignature(dspy.Signature):
    """
    You are the HELP-DESK router-agent. Your job is to inspect an incoming user request (plain text) and decide which of the available agents should handle the request. Agents available: account-agent, billing-agent, tech-agent, security-agent, compliance-agent, cx-agent. You must return ONLY valid JSON (no extra commentary) that conforms to the Pydantic model RouterOutput with this schema: {"selected_agents": [string], "reasoning": {"tech-agent": string, "billing-agent": string, "account-agent": string, "security-agent": string, "compliance-agent": string, "cx-agent": string}, "confidence": {"tech-agent": number, "billing-agent": number, "account-agent": number, "security-agent": number, "compliance-agent": number, "cx-agent": number}}. Routing rules: select an agent when the prompt contains primary signals for that domain (connectivity/devices -> tech-agent; charges/refunds/invoices -> billing-agent; identity/subscription/ownership -> account-agent; suspicious/login/fraud indicators -> security-agent; PII/legal/data requests (e.g., GDPR, privacy, delete, subpoena, DMCA) -> compliance-agent; angry/upset tone or high CSAT risk -> cx-agent). Use the following keyword lists as ASAP signals: PII/legal keywords = ["GDPR","privacy","delete","export","subpoena","DMCA"], security keywords = ["suspicious","unknown device","foreign country","takeover","unauthorized","account takeover","unexpected login"], payment keywords = ["invoice","charged","refund","double charge","overcharged","payment failed"], account keywords = ["password","login","reset","subscription","cancel","account"], tech keywords = ["error","500","crash","latency","load","stream","bug","not working"], sentiment indicators = [angry, upset, frustrated, please help, furious]. Select multiple agents when domains appear together. Favor inclusion (high recall) when uncertain: include an agent if a signal appears OR the intent classifier suggests it (prefer more agents over missing one). Provide short reasoning for each agent (<=2 sentences) explaining why it was included or excluded and numeric confidences 0.0-1.0 for each agent. Example output must include keys for all six agents in both reasoning and confidence. Return only JSON and ensure the JSON parses. Do not include extra text.
    """
    text = dspy.InputField(desc="The incoming user request")
    selected_agents = dspy.OutputField(desc="List of selected agent IDs")
    reasoning = dspy.OutputField(desc="Reasoning for each agent as a dictionary")
    confidence = dspy.OutputField(desc="Confidence scores for each agent as a dictionary")

class RouterModule(dspy.Module):
    def __init__(self, system_prompt):
        super().__init__()
        self.router = dspy.ChainOfThought(RouterSignature.with_instructions(system_prompt))

    def forward(self, text):
        return self.router(text=text)

class AgentPayloadProcessor:
    def prepare_payload(self, task: AgentTask):
        data = task.job_data
        text = data.get("text", "")
        communication_type = data.get("communication_type", "p2p")
        model_name = data.get("model_name", "aios:qwen3-1-7b-vllm-block")
        session_id = data.get("session_id", str(uuid.uuid4()))
        return text, communication_type, model_name, session_id

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

class ContentParser:
    @staticmethod
    def parse_router_result(result):
        def parse_if_string(val):
            if isinstance(val, str):
                try:
                    return json.loads(val)
                except:
                    return val
            return val

        selected_agents = parse_if_string(result.selected_agents)
        reasoning = parse_if_string(result.reasoning)
        confidence = parse_if_string(result.confidence)

        return {
            "selected_agents": selected_agents,
            "reasoning": reasoning,
            "confidence": confidence
        }

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

        # Initialize DSPy helpers
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        self.module = RouterModule(self.persona_default_system_message)
        self.payload_processor = AgentPayloadProcessor()
        self.model_context = ModelContextManager(self.aios_dspy_lm)
        self.content_parser = ContentParser()

        # Dynamic Selection Logic
        try:
            params = self.subject.persona.config['parameters']
            INFERENCE_SERVER_REGISTRY_URL = params['INFERENCE_SERVER_REGISTRY_URL']
            BLOCKS_DB_URL = params['BLOCKS_DB_URL']
            INFERENCE_SERVER_ID = params['INFERENCE_SERVER_ID']
            AGENT_SELECTOR_LLM = params['AGENT_SELECTOR_LLM']

            known_agents = KnownAgents(default_compact=False)
            known_agents.query_and_add(query={
                "metadata.subject_search_tags": "help-desk"
            })
            self.all_agent_ids = [agent.id for agent in known_agents.list_all()]
            log.info("Known agents for help-desk: %s", self.all_agent_ids)

            mgr = AgentSearchSelector()
            mgr.register_new_selector(
                name="default",
                model=AGENT_SELECTOR_LLM,
                inference_server_id=INFERENCE_SERVER_ID,
                aios_url_map={
                    "inference_server_url": INFERENCE_SERVER_REGISTRY_URL,
                    "blocks_db_url": BLOCKS_DB_URL,
                }
            )

            chosen_id = mgr.search_from_objects(
                name="default",
                objects=known_agents.list_all(),
                query="For routing task in help-desk related",
            )
            self.chosen_agent_id = chosen_id
            log.info("Chosen ID: %s", self.chosen_agent_id)
        except Exception as e:
            log.error(f"Failed to initialize dynamic selection: {e}")
            self.chosen_agent_id = "unknown"

    def get_muxer(self):
        return None

    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        # job_data --> exchange, task --> mesh
        # in exchange, we are positng jobs conceptually
        # in mesh --> we directly submit events
        log.info(f"Preprocessing task {task.task_id} {task.job_data}")
        text = task.job_data.get("text")
        if not text:
            # log.warning("Task %s has no 'text' in job_data, skipping.", task.task_id)
             pass
        return [task]

    def _prepare_inputs(self, task: AgentTask):
        return self.payload_processor.prepare_payload(task)

    def _execute_worker(self, text, model_name, session_id):
        with self.model_context.get_context(model_name=model_name, session_id=session_id):
            return self.module.forward(text=text)

    def _prepare_synthesizer_packet(self, session_id, model_name, text, router_output, communication_type, mux_size):
        return {
            "mux_size": mux_size,
            "session_id": session_id,
            "model_name": model_name,
            "original_user_request": text,
            "router_output": router_output,
            "communication_type": communication_type
        }

    def _route_to_specialized_agents(self, task, next_agent_subject_id_list, input_to_next_agent, session_id, model_name, communication_type):
        for next_agent_id in next_agent_subject_id_list:
            log.info(f"Preparing to call specialized agent: {next_agent_id} via {communication_type}")
            
            agent_session_id = str(uuid.uuid4())
            data_for_agent = {
                "text": input_to_next_agent,
                "session_id": agent_session_id,
                "model_name": model_name,
                "communication_type": communication_type
            }

            if communication_type == "p2p":
                self.context.p2p_manager.send_sync(
                    task=task, subject_id=next_agent_id,
                    job_data=data_for_agent, 
                    session_id=session_id
                )
            elif communication_type == "direct":
                self.context.direct.submit(to=next_agent_id, session_id=session_id, task=task, job_data=data_for_agent)
            elif communication_type == "delegate":
                log.info(f"Delegating specialized task to {next_agent_id}")
                self.context.delegator.submit(
                    subject_id=next_agent_id, session_id=session_id,
                    task_id=task.task_id, task_data=data_for_agent
                )
            else:
                self.context.direct.submit(to=next_agent_id, session_id=session_id, task=task, job_data=data_for_agent)

    def on_data(self, task: AgentTask) -> AgentResult:
        try:
            text, communication_type, model_name, session_id = self._prepare_inputs(task)
            log.info(f"[{self.chosen_agent_id}] Routing user request: {text}")

            # 1. Run DSPy Module
            llm_session_id = str(uuid.uuid4())
            result = self._execute_worker(text, model_name, llm_session_id)
            log.info(f"Router Result: {result}")

            # 2. Parse results
            router_output = self.content_parser.parse_router_result(result)
            selected_agents = router_output["selected_agents"]
            
            if not isinstance(selected_agents, list):
                log.warning(f"Unexpected type for selected_agents: {type(selected_agents)}. Defaulting to empty list.")
                selected_agents = []

            # 3. Call synthesizer first to set mux size
            synthesizer_agent_id = "synthesizer-agent"
            mux_size = len(selected_agents)
            mux_data = self._prepare_synthesizer_packet(session_id, model_name, text, router_output, communication_type, mux_size)

            log.info(f"Communicating to {synthesizer_agent_id} via {communication_type} with mux_size={mux_size}")
            
            if communication_type == "delegate":
                log.info(f"Delegating to {synthesizer_agent_id}")
                self.context.delegator.submit(
                    subject_id=synthesizer_agent_id, session_id=session_id,
                    task_id=task.task_id, task_data=mux_data
                )
            elif communication_type == "p2p":
                self.context.p2p_manager.send_sync(
                    task=task, subject_id=synthesizer_agent_id,
                    job_data=mux_data,
                    session_id=session_id
                )
            elif communication_type == "direct":
                self.context.direct.submit(to=synthesizer_agent_id, session_id=session_id, task=task, job_data=mux_data)
            else:
                self.context.delegator.submit(
                    subject_id=synthesizer_agent_id, session_id=session_id,
                    task_id=task.task_id, task_data=mux_data
                )

            # 4. Route to specialized agents
            input_to_next_agent = f"---ORIGINAL_USER_REQUEST---\n{text}\n---OUTPUT---\n{json.dumps(router_output)}"
            self._route_to_specialized_agents(task, selected_agents, input_to_next_agent, session_id, model_name, communication_type)

            return AgentResult(
                task_id=task.task_id,
                skip=True
            )

        except Exception as e:
            log.exception(f"Error in Router Agent: {e}")
            return AgentResult(
                task_id=task.task_id,
                is_error=True,
                error_data={"message": str(e)},
            )

if __name__ == "__main__":
    main(SampleAgent)
