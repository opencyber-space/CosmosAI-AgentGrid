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
from utils.help_desk_pydatic_models import validate_helpdesk_llm_output, AccountOutput

log = logging.getLogger(__name__)

# --- DSPy Signatures ---
class AccountSignature(dspy.Signature):
    """
    You are HELP-DESK account-agent. Input: a formatted string containing "---ORIGINAL_USER_REQUEST---" and "---OUTPUT---" (the router's JSON output). You must return ONLY valid JSON that conforms to the Pydantic model AccountOutput with this schema: {"domain":"account","summary":string,"current_account_state":string | "unknown","actions":[{"who":"user|system|agent","action":string,"estimated_time_minutes":int,"priority":"low|medium|high"}],"security_notes":[string],"required_info":[string],"escalation": {"escalate_to":string,"reason":string} | null}. Behavior: If router output's selected_agents does NOT include "account-agent", RETURN A FULL VALID MINIMAL AccountOutput object. Example minimal valid object to return when not selected: {"domain":"account","summary":"Not Applicable","current_account_state":"unknown","actions":[],"security_notes":[],"required_info":[],"escalation":null}. Prioritize account security; list exact verification fields if identity checks are required. Return only JSON matching AccountOutput exactly. Ensure JSON parses.
    """
    text = dspy.InputField(desc="The formatted input containing original_user_request and router_output")
    account_output = dspy.OutputField(desc="JSON matching AccountOutput schema")

class AccountModule(dspy.Module):
    def __init__(self, system_prompt):
        super().__init__()
        self.account_expert = dspy.ChainOfThought(AccountSignature.with_instructions(system_prompt))

    def forward(self, text):
        return self.account_expert(text=text)

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
            "domain": "account",
            "summary": "Not Applicable",
            "current_account_state": "unknown",
            "actions": [],
            "security_notes": [],
            "required_info": [],
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
        self.module = AccountModule(self.persona_default_system_message)
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
        text = task.job_data.get("text")
        # if not text:
        #     log.warning(
        #         "Task %s has no 'text' in job_data, skipping.", task.task_id)
        #     return None

        return [task]

    def on_data(self, task: AgentTask) -> AgentResult:
        try:
            input_text = task.job_data.get("text", "")
            communication_type = task.job_data.get("communication_type", "p2p")
            model_name = task.job_data.get("model_name", "aios:qwen3-1-7b-vllm-block")
            session_id = task.job_data.get("session_id", str(uuid.uuid4()))

            # Parse input_text
            try:
                parts = input_text.split("---OUTPUT---")
                original_user_request = parts[0].replace("---ORIGINAL_USER_REQUEST---", "").strip()
                router_output = json.loads(parts[1].strip())
            except Exception as e:
                log.error(f"Failed to parse input_text: {e}")
                original_user_request = ""
                router_output = {}

            log.info(f"[account-agent] Processing request: {original_user_request}")

            # 1. Check if selected by router
            selected_agents = router_output.get("selected_agents", [])
            if "account-agent" not in selected_agents:
                log.info("account-agent not selected by router. Returning minimal output.")
                out_account = {
                    "domain": "account",
                    "summary": "Not Applicable",
                    "current_account_state": "unknown",
                    "actions": [],
                    "security_notes": [],
                    "required_info": [],
                    "escalation": None
                }
            else:
                # 2. Run DSPy Module
                llm_session_id = str(uuid.uuid4())
                with dspy.settings.context(lm=self.aios_dspy_lm.get_choosen_model(model_name=model_name, session_id=llm_session_id)):
                    result = self.module.forward(text=input_text)
                
                out_account = result.account_output
                if isinstance(out_account, str):
                    try:
                        out_account = json.loads(out_account)
                    except:
                        pass

            log.info(f"Account Result: {out_account}")
            
            # 3. Prepare for next agent (synthesizer)
            try:
                next_agent_subject_id = self.agents_config["help-desk"]["account-agent"]["next_agent"]
            except (KeyError, TypeError):
                log.warning("next_agent not found in config for account-agent. Defaulting to synthesizer-agent.")
                next_agent_subject_id = "synthesizer-agent"

            log.info(f"Submitting result to {next_agent_subject_id}")

            agent_session_id = session_id
            job_data = {
                "account_output": out_account,
                "session_id": agent_session_id,
                "model_name": model_name,
                "communication_type": communication_type
            }

            # if communication_type == "delegate":
            #     log.info(f"Delegating to {next_agent_subject_id} agent via delegator.")
            #     op_x = self.context.delegator.submit_and_wait(
            #         subject_id=next_agent_subject_id, session_id=agent_session_id,
            #         task_id=task.task_id, task_data=job_data
            #     )
            if communication_type == "p2p":
                log.info(f"Communicating to {next_agent_subject_id} agent via p2p_manager.")
                #commu = random.choice(["delegate","p2p","direct"])
                self.context.p2p_manager.send_sync(
                    task=task, subject_id=next_agent_subject_id,
                    job_data=job_data, 
                    session_id=agent_session_id
                )
            elif communication_type == "direct":
                log.info(f"Communicating to {next_agent_subject_id} agent via direct.")
                #commu = random.choice(["delegate","p2p","direct"])
                # agent direct (doesn't return the result to the caller)
                self.context.direct.submit(to=next_agent_subject_id, session_id=agent_session_id, task=task, job_data=job_data)
            else:
                log.info(f"Communicating to {next_agent_subject_id} agent via direct.")
                #commu = random.choice(["delegate","p2p","direct"])
                # agent direct (doesn't return the result to the caller)
                self.context.direct.submit(to=next_agent_subject_id, session_id=agent_session_id, task=task, job_data=job_data)

            return AgentResult(task_id=task.task_id, skip=True)

        except Exception as e:
            log.exception(f"Error in Account Agent: {e}")
            return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})

if __name__ == "__main__":
    main(SampleAgent)
