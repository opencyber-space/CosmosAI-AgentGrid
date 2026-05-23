import logging, json, yaml, os, uuid
from typing import List, Optional
import dspy

from agents_sdk.core.agent_executor import AgentTask, AgentResult, Context
from agents_sdk.core.main import main
from utils.dspy_aios_llms import AIOS_DSPy_LMs

log = logging.getLogger(__name__)

# --- DSPy Signatures ---
class InvitationSignature(dspy.Signature):
    """
    You are a Meeting Invitation Crafter.
    Draft a professional email invitation for a meeting based on the goal, brainstormed topics, and structured agenda.
    Include a clear subject line and a polite call to action.
    Ensure the invitation's tone and content are consistent with the meeting's duration and goals.
    """
    meeting_goal = dspy.InputField(desc="The main objective or goal of the meeting")
    brainstormed_topics = dspy.InputField(desc="The core topics identified for the meeting")
    agenda = dspy.InputField(desc="The structured, timed agenda")
    email_invitation = dspy.OutputField(desc="The complete, professional email invitation text")

class InvitationModule(dspy.Module):
    def __init__(self, system_prompt):
        super().__init__()
        self.worker = dspy.ChainOfThought(InvitationSignature.with_instructions(system_prompt))

    def forward(self, meeting_goal, brainstormed_topics, agenda):
        return self.worker(meeting_goal=meeting_goal, brainstormed_topics=brainstormed_topics, agenda=agenda)

class AgentPayloadProcessor:
    def prepare_payload(self, task: AgentTask):
        data = task.job_data
        input_text = data.get("text", "")
        model_name = data.get("model_name", "aios:qwen3-1-7b-vllm-block")
        session_id = data.get("session_id", str(uuid.uuid4()))

        try:
            state = json.loads(input_text)
            meeting_goal = state.get("meeting_goal", "")
            brainstormed_topics = state.get("brainstormed_topics", "")
            agenda = state.get("agenda", "")
        except Exception as e:
            log.error(f"Failed to parse accumulated state: {e}. Using raw text as goal.")
            meeting_goal = input_text
            brainstormed_topics = "N/A"
            agenda = "N/A"
            state = {"meeting_goal": meeting_goal}

        return state, meeting_goal, brainstormed_topics, agenda, model_name, session_id

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
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        self.module = InvitationModule(self.persona_default_system_message)
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

    def _execute_worker(self, meeting_goal, brainstormed_topics, agenda, model_name, session_id):
        with self.model_context.get_context(model_name=model_name, session_id=session_id):
            return self.module(meeting_goal=meeting_goal, brainstormed_topics=brainstormed_topics, agenda=agenda)

    def on_data(self, task: AgentTask) -> AgentResult:
        try:
            state, meeting_goal, brainstormed_topics, agenda, model_name, session_id = self._prepare_inputs(task)
            log.info(f"Crafting invitation for goal: {meeting_goal}")

            # 1. Run DSPy Module
            llm_session_id = str(uuid.uuid4())
            result = self._execute_worker(meeting_goal, brainstormed_topics, agenda, model_name, llm_session_id)
            
            invitation = result.email_invitation
            log.info(f"Generated Invitation: {invitation[:100]}...")

            # 2. Determine next agent from config
            next_agent_subject_id = self.agents_config.get("meeting", {}).get(self.subject.identity.subject_id, {}).get("next_agent")
            
            if not next_agent_subject_id:
                log.info("No next agent configured. Returning final result.")
                return AgentResult(
                    task_id=task.task_id,
                    job_output={"text": invitation},
                    job_output_metadata={"length": len(invitation)},
                    is_error=False,
                )

            # (Default to returning final result for crafter if no next agent is found)
            return AgentResult(
                task_id=task.task_id,
                job_output={"text": invitation},
                job_output_metadata={"length": len(invitation)},
                is_error=False,
            )

        except Exception as e:
            log.exception(f"Error in Meeting Invitation Crafter: {e}")
            return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})

if __name__ == "__main__":
    main(SampleAgent)
