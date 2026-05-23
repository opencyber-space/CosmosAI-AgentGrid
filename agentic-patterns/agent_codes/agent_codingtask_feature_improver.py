import logging, json, yaml, os, uuid
from typing import List, Optional
import dspy

from agents_sdk.core.agent_executor import AgentTask, AgentResult
from agents_sdk.core.main import main
from agents_sdk.core.agent_executor import Context
from utils.dspy_aios_llms import AIOS_DSPy_LMs, clean_json_string

log = logging.getLogger(__name__)

# --- DSPy Signatures ---
class FeatureImproverSignature(dspy.Signature):
    """
    You are Agent6 ‘FeatRefiner’. Given normalized_text that may include a short code snippet and notes,
    produce a complete, actionable feature request without inventing facts.
    Tasks:
    1) Structure into sections: Title, User Problem, Proposed Change, Design Notes, Acceptance Criteria,
       Non‑Goals, Risks/Trade‑offs, Open Questions; write ‘Unknown’ if a field is missing.
    2) Keep between 120 and 180 words excluding code.
    3) Preserve terminology, CLI flags, config names, and defaults exactly; do not change semantics.
    4) Acceptance Criteria must be concrete, testable bullet points.
    
    The improved_markdown must use H2 headings (## Title, ## User Problem, ## Proposed Change, ## Design Notes,
    ## Acceptance Criteria, ## Non‑Goals, ## Risks/Trade‑offs, ## Open Questions).

    Output fields:
    1) improved_markdown: Report in Markdown with H2 headings
    2) improved_code: The full improved code snippet. You MUST provide the complete updated code here if the request involves code changes.
    3) key_sections_present: List of sections not equal to ‘Unknown’ (comma-separated)
    4) actionable_checks: List of status flags (comma-separated), e.g., ‘has_user_problem’, ‘has_acceptance’, ‘has_non_goals’, ‘has_risks’.
    """
    normalized_text = dspy.InputField(desc="The normalized text containing code and notes")
    improved_markdown = dspy.OutputField(desc="Report in Markdown with H2 headings")
    improved_code = dspy.OutputField(desc="The complete improved code snippet")
    key_sections_present = dspy.OutputField(desc="List of present sections (comma-separated)")
    actionable_checks = dspy.OutputField(desc="List of status flags (comma-separated)")

# --- DSPy Modules ---
class FeatureImproverModule(dspy.Module):
    def __init__(self, system_prompt):
        super().__init__()
        self.cot = dspy.ChainOfThought(FeatureImproverSignature.with_instructions(system_prompt))

    def forward(self, normalized_text):
        return self.cot(normalized_text=normalized_text)

class AgentPayloadProcessor:
    def prepare_payload(self, task: AgentTask):
        data = task.job_data
        input_text = data.get("text", "")
        communication_type = data.get("communication_type", "p2p")
        model_name = data.get("model_name", "aios:qwen3-1-7b-vllm-block")
        session_id = data.get("session_id", str(uuid.uuid4()))

        try:
            state = json.loads(input_text)
            normalized_text = state.get("normalized_text", input_text)
        except Exception as e:
            log.error(f"Failed to parse incoming state: {e}. Using raw text.")
            normalized_text = input_text
            state = {"input_text": input_text}

        return state, normalized_text, communication_type, model_name, session_id

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
    def to_list(self, s):
        if not s: return []
        if isinstance(s, list): return s
        return [i.strip() for i in s.split(",") if i.strip()]

class SampleAgent:

    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        self.persona_default_system_message = self.subject.persona.default_system_message
        self.aios_dspy_lm = AIOS_DSPy_LMs(self.subject)
        self.module = FeatureImproverModule(self.persona_default_system_message)
        self.payload_processor = AgentPayloadProcessor()
        self.model_context = ModelContextManager(self.aios_dspy_lm)
        self.parser = ContentParser()
        
        # Load agents_config.yaml
        config_path = os.path.join(os.path.dirname(__file__), "agents_config.yaml")
        try:
            with open(config_path, "r") as f:
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

    def _execute_worker(self, normalized_text, model_name, session_id):
        with self.model_context.get_context(model_name=model_name, session_id=session_id):
            return self.module(normalized_text=normalized_text)

    def on_data(self, task: AgentTask) -> AgentResult:
        try:
            state, normalized_text, communication_type, model_name, session_id = self._prepare_inputs(task)
            log.info(f"Processing feature request for normalized text: {normalized_text[:100]}...")

            # 1. Run DSPy Module
            llm_session_id = str(uuid.uuid4())
            result = self._execute_worker(normalized_text, model_name, llm_session_id)
            
            # Construct JSON manually for robustness
            improved_markdown = getattr(result, "improved_markdown", "")
            improved_code = getattr(result, "improved_code", "None")
            key_sections = getattr(result, "key_sections_present", "")
            actionable_checks = getattr(result, "actionable_checks", "")
            
            key_sections_list = self.parser.to_list(key_sections)
            actionable_checks_list = self.parser.to_list(actionable_checks)

            output_json_str = json.dumps({
                "improved_markdown": improved_markdown,
                "improved_code": improved_code,
                "key_sections_present": key_sections_list,
                "actionable_checks": actionable_checks_list
            })
            
            # 3. Update and Package state
            state["feature_request_json"] = output_json_str
            state["improved_markdown"] = improved_markdown
            state["improved_code"] = improved_code
            state["key_sections_present"] = key_sections_list
            state["actionable_checks"] = actionable_checks_list

            # 5. Package and propagate state
            state["feature_request"] = output_json_str
            input_to_next_agent = json.dumps(state)

            # Determine next agent from config
            next_agent_subject_id = self.agents_config.get("coding-task", {}).get(self.subject.identity.subject_id, {}).get("next_agent")
            
            if not next_agent_subject_id or next_agent_subject_id == "false":
                log.info("No next agent configured. Finishing flow.")
                return AgentResult(task_id=task.task_id, job_output={"text": input_to_next_agent})

            log.info(f"Preparing to call next agent: {next_agent_subject_id} with communication type: {communication_type}")
            
            task_data = {
                "text": input_to_next_agent,
                "session_id": session_id,
                "model_name": model_name,
                "communication_type": communication_type
            }

            if communication_type == "p2p":
                log.info(f"Communicating to {next_agent_subject_id} agent via p2p_manager.")
                op_x = self.context.p2p_manager.send_and_wait_sync(
                    task.task_id, subject_id=next_agent_subject_id,
                    task_data=task_data
                )
            elif communication_type == "delegate":
                 log.info(f"Delegating to {next_agent_subject_id} agent via delegator.")
                 op_x = self.context.delegator.submit_and_wait(
                    subject_id=next_agent_subject_id, session_id=session_id,
                    task_id=task.task_id, task_data=task_data
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
                job_output_metadata={"length": len(input_to_next_agent)},
                is_error=False,
            )

        except Exception as e:
            log.exception("Error processing task %s: %s", task.task_id, e)
            return AgentResult(
                task_id=task.task_id,
                is_error=True,
                error_data={"stage": "on_data", "message": str(e)},
            )

main(SampleAgent)
