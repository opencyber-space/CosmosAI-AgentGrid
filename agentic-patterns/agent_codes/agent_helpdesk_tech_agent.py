import logging
import uuid
import yaml
import json
import dspy
from typing import List, Optional

from agents_sdk.core.agent_executor import AgentTask, AgentResult, Context
from agents_sdk.core.main import main
from agents_sdk.core.known_agents import KnownAgents
from agents_search.search import AgentSearchSelector
from utils.dspy_aios_llms import AIOS_DSPy_LMs
from utils.help_desk_pydatic_models import validate_helpdesk_llm_output, TechOutput

log = logging.getLogger(__name__)

# --- DSPy Signatures ---
class TechSignature(dspy.Signature):
    """
    You are HELP-DESK tech-agent. Input: a formatted string containing "---ORIGINAL_USER_REQUEST---" and "---OUTPUT---" (the router's JSON output). You must return ONLY valid JSON that conforms to the Pydantic model TechOutput with this schema: {"domain":"tech","summary":string,"hardware_related":boolean,"software_related":boolean,"actions":[{"who":"user|system|agent","action":string,"estimated_time_minutes":int,"priority":"low|medium|high"}],"troubleshooting_steps":[string],"escalation": {"escalate_to":"l2_support|dev_ops|engineering","reason":string} | null}. Behavior: If router output's selected_agents does NOT include "tech-agent", RETURN A FULL VALID MINIMAL TechOutput object. Example minimal valid object to return when not selected: {"domain":"tech","summary":"Not Applicable","hardware_related":false,"software_related":false,"actions":[],"troubleshooting_steps":[],"escalation":null}. Focus on technical issues, bug reports, and hardware failures. Return only JSON matching TechOutput exactly. Ensure JSON parses.
    """
    text = dspy.InputField(desc="The formatted input containing original_user_request and router_output")
    tech_output = dspy.OutputField(desc="JSON matching TechOutput schema")

class TechModule(dspy.Module):
    def __init__(self, system_prompt):
        super().__init__()
        self.tech_expert = dspy.ChainOfThought(TechSignature.with_instructions(system_prompt))

    def forward(self, text):
        return self.tech_expert(text=text)

class AgentPayloadProcessor:
    def prepare_payload(self, task: AgentTask):
        data = task.job_data
        input_text = data.get("text", "")
        communication_type = data.get("communication_type", "p2p")
        model_name = data.get("model_name", "aios:qwen3-1-7b-vllm-block")
        session_id = data.get("session_id", str(uuid.uuid4()))
        return input_text, communication_type, model_name, session_id

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
    def parse_input_text(input_text: str):
        try:
            parts = input_text.split("---OUTPUT---")
            original_user_request = parts[0].replace("---ORIGINAL_USER_REQUEST---", "").strip()
            router_output = json.loads(parts[1].strip())
            return original_user_request, router_output
        except Exception as e:
            log.error(f"Failed to parse input_text: {e}")
            return "", {}

    @staticmethod
    def get_minimal_output():
        return {
            "domain": "tech",
            "summary": "Not Applicable",
            "hardware_related": False,
            "software_related": False,
            "actions": [],
            "troubleshooting_steps": [],
            "escalation": None
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
        self.module = TechModule(self.persona_default_system_message)
        self.payload_processor = AgentPayloadProcessor()
        self.model_context = ModelContextManager(self.aios_dspy_lm)
        self.content_parser = ContentParser()

    def get_muxer(self):
        return None

    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        # job_data --> exchange, task --> mesh
        # in exchange, we are positng jobs conceptually
        # in mesh --> we directly submit events
        log.info(f"Preprocessing task {task.task_id} {task.job_data}")
        return [task]

    def _prepare_inputs(self, task: AgentTask):
        return self.payload_processor.prepare_payload(task)

    def _execute_worker(self, input_text, original_user_request, router_output, model_name, session_id):
        selected_agents = router_output.get("selected_agents", [])
        if "tech-agent" not in selected_agents:
            log.info("tech-agent not selected by router. Returning minimal output.")
            return self.content_parser.get_minimal_output()
        
        log.info(f"[tech-agent] Processing request: {original_user_request}")
        llm_session_id = str(uuid.uuid4())
        with self.model_context.get_context(model_name=model_name, session_id=llm_session_id):
            result = self.module.forward(text=input_text)
        
        out_tech = result.tech_output
        if isinstance(out_tech, str):
            try:
                out_tech = json.loads(out_tech)
            except:
                pass
        return out_tech

    def on_data(self, task: AgentTask) -> AgentResult:
        try:
            input_text, communication_type, model_name, session_id = self._prepare_inputs(task)
            original_user_request, router_output = self.content_parser.parse_input_text(input_text)

            # 1. Run worker
            out_tech = self._execute_worker(input_text, original_user_request, router_output, model_name, session_id)
            log.info(f"Tech Result: {out_tech}")
            
            # 2. Prepare for next agent (synthesizer)
            try:
                next_agent_id = self.agents_config["help-desk"]["tech-agent"]["next_agent"]
            except (KeyError, TypeError):
                log.warning("next_agent not found in config for tech-agent. Defaulting to synthesizer-agent.")
                next_agent_id = "synthesizer-agent"

            log.info(f"Submitting result to {next_agent_id} via {communication_type}")

            job_data = {
                "tech_output": out_tech,
                "session_id": session_id,
                "model_name": model_name,
                "communication_type": communication_type
            }

            if communication_type == "p2p":
                self.context.p2p_manager.send_sync(
                    task=task, subject_id=next_agent_id,
                    job_data=job_data, 
                    session_id=session_id
                )
            elif communication_type == "direct":
                self.context.direct.submit(to=next_agent_id, session_id=session_id, task=task, job_data=job_data)
            elif communication_type == "delegate":
                self.context.delegator.submit(
                    subject_id=next_agent_id, session_id=session_id,
                    task_id=task.task_id, task_data=job_data
                )
            else:
                self.context.direct.submit(to=next_agent_id, session_id=session_id, task=task, job_data=job_data)

            return AgentResult(task_id=task.task_id, skip=True)

        except Exception as e:
            log.exception(f"Error in Tech Agent: {e}")
            return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})

if __name__ == "__main__":
    main(SampleAgent)
