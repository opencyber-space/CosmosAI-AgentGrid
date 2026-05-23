import logging, json, yaml, os, uuid
from typing import List, Optional
import dspy

from agents_sdk.core.agent_executor import AgentTask, AgentResult, Context
from agents_sdk.core.main import main
from utils.dspy_aios_llms import AIOS_DSPy_LMs

log = logging.getLogger(__name__)

# --- DSPy Signatures ---
class AgendaSignature(dspy.Signature):
    """
    You are a Meeting Agenda Architect.
    
    STRICT CONSTRAINT: Your agenda MUST NOT exceed the total duration specified in the meeting goal.
    
    INSTRUCTIONS:
    1. EXTRACT LIMIT: Identify the total duration (e.g., "1 hour" = 60 minutes).
    2. GROUP TOPICS: Select/group the brainstormed topics to fit.
    3. MATH VERIFICATION: Calculate the duration of each slot in minutes. SUM THEM UP.
    4. FINAL CHECK: If the sum > limit, you MUST combine or remove items until the sum <= limit.
    5. FORMAT: Use start/end times (e.g., 9:00 - 9:15).
    """
    meeting_goal = dspy.InputField(desc="The main objective or goal of the meeting")
    brainstormed_topics = dspy.InputField(desc="A raw list of topics to be organized into an agenda")
    agenda = dspy.OutputField(desc="A structured, timed agenda (e.g., '9:00 - 9:15: Introduction')")

class AgendaModule(dspy.Module):
    def __init__(self, system_prompt):
        super().__init__()
        self.worker = dspy.ChainOfThought(AgendaSignature.with_instructions(system_prompt))

    def forward(self, meeting_goal, brainstormed_topics):
        return self.worker(meeting_goal=meeting_goal, brainstormed_topics=brainstormed_topics)

class AgentPayloadProcessor:
    def prepare_payload(self, task: AgentTask):
        data = task.job_data
        input_text = data.get("text", "")
        communication_type = data.get("communication_type", "p2p")
        model_name = data.get("model_name", "aios:qwen3-1-7b-vllm-block")
        session_id = data.get("session_id", str(uuid.uuid4()))

        try:
            state = json.loads(input_text)
            meeting_goal = state.get("meeting_goal", "")
            brainstormed_topics = state.get("brainstormed_topics", "")
        except Exception as e:
            log.error(f"Failed to parse incoming state: {e}. Using raw text as goal.")
            meeting_goal = input_text
            brainstormed_topics = "N/A"
            state = {"meeting_goal": meeting_goal}

        return state, meeting_goal, brainstormed_topics, communication_type, model_name, session_id

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
        self.module = AgendaModule(self.persona_default_system_message)
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

    def _execute_worker(self, meeting_goal, brainstormed_topics, model_name, session_id):
        with self.model_context.get_context(model_name=model_name, session_id=session_id):
            return self.module(meeting_goal=meeting_goal, brainstormed_topics=brainstormed_topics)

    def on_data(self, task: AgentTask) -> AgentResult:
        try:
            state, meeting_goal, brainstormed_topics, communication_type, model_name, session_id = self._prepare_inputs(task)
            log.info(f"Architecting agenda for goal: {meeting_goal}")

            # 1. Run DSPy Module
            llm_session_id = str(uuid.uuid4())
            result = self._execute_worker(meeting_goal, brainstormed_topics, model_name, llm_session_id)
            
            agenda = result.agenda
            log.info(f"Generated Agenda: {agenda[:100]}...")

            # 2. Update and Package state
            state["agenda"] = agenda
            payload_text = json.dumps(state)

            # 3. Determine next agent from config
            next_agent_subject_id = self.agents_config.get("meeting", {}).get(self.subject.identity.subject_id, {}).get("next_agent")
            
            if not next_agent_subject_id:
                log.info("No next agent configured. Finishing flow.")
                return AgentResult(task_id=task.task_id, job_output={"text": payload_text})

            log.info(f"Preparing to call next agent: {next_agent_subject_id} with communication type: {communication_type}")
            
            op_x = None
            task_data = {
                "text": payload_text,
                "session_id": session_id,
                "model_name": model_name,
                "communication_type": communication_type
            }

            if communication_type == "delegate":
                log.info(f"Delegating to {next_agent_subject_id} agent via delegator.")
                op_x = self.context.delegator.submit_and_wait(
                    subject_id=next_agent_subject_id, session_id=session_id,
                    task_id=task.task_id, task_data=task_data
                )
            elif communication_type == "p2p":
                log.info(f"Communicating to {next_agent_subject_id} agent via p2p_manager.")
                op_x = self.context.p2p_manager.send_and_wait_sync(
                    task.task_id, subject_id=next_agent_subject_id,
                    task_data=task_data
                )
            elif communication_type == "direct":
                log.info(f"Communicating to {next_agent_subject_id} agent via direct.")
                self.context.direct.submit(to=next_agent_subject_id, session_id=session_id, task=task, job_data=task_data)
                return AgentResult(
                    task_id=task.task_id,
                    skip=True
                )
            else:
                log.info(f"Communicating to {next_agent_subject_id} agent via fallback.")
                op_x = self.context.delegator.submit_and_wait(
                    subject_id=next_agent_subject_id, session_id=session_id,
                    task_id=task.task_id, task_data=task_data
                )

            return AgentResult(
                task_id=task.task_id,
                job_output=op_x,
                job_output_metadata={"length": len(agenda)},
                is_error=False,
            )

        except Exception as e:
            log.exception(f"Error in Meeting Agenda Architect: {e}")
            return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})

if __name__ == "__main__":
    main(SampleAgent)
