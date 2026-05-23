import logging, json, yaml, os, uuid
from typing import List, Optional
import dspy

from agents_sdk.core.agent_executor import AgentTask, AgentResult
from agents_sdk.core.main import main
from agents_sdk.core.agent_executor import Context
from utils.dspy_aios_llms import AIOS_DSPy_LMs, clean_json_string

log = logging.getLogger(__name__)

# --- DSPy Signatures ---
class AggregatorSignature(dspy.Signature):
    """
    You are Agent9 ‘TriageSummarizer’. Synthesize a standardized triage summary from a single upstream branch (bug or feature). Do not invent facts.
    Tasks:
    1) Parse the upstream input which contains improved_markdown, key_sections_present, and actionable_checks.
    2) Extract the corresponding code snippet from the input (either 'corrected_code' if it's a bug or 'improved_code' if it's a feature).
    3) title: take from the first heading or a clear first sentence.
    4) one_line_summary: neutral, specific, ≤120 characters.
    5) body_markdown: pass through improved_markdown unchanged except trivial whitespace fixes.
    6) quality_flags: infer gaps using key_sections_present and actionable_checks (e.g., ‘missing_repro_steps’, ‘missing_environment’, ‘missing_acceptance_criteria’, ‘no_risks’).

    Output fields:
    1) type: 'bug' or 'feature'
    2) title: Short descriptive title
    3) one_line_summary: Concise neutral summary
    4) body_markdown: Full report in Markdown
    5) quality_flags: Comma-separated status flags
    6) final_code: The full corrected/improved code snippet (if applicable, else 'None')
    """
    report_json = dspy.InputField(desc="The JSON string containing the bug report or feature request and state")
    type = dspy.OutputField(desc="'bug' or 'feature'")
    title = dspy.OutputField(desc="Short title")
    one_line_summary = dspy.OutputField(desc="Concise summary")
    body_markdown = dspy.OutputField(desc="Full report in Markdown")
    quality_flags = dspy.OutputField(desc="Comma-separated status flags")
    final_code = dspy.OutputField(desc="The full corrected/improved code snippet")

# --- DSPy Modules ---
class AggregatorModule(dspy.Module):
    def __init__(self, system_prompt):
        super().__init__()
        self.cot = dspy.ChainOfThought(AggregatorSignature.with_instructions(system_prompt))

    def forward(self, report_json):
        return self.cot(report_json=report_json)

class AgentPayloadProcessor:
    def prepare_payload(self, task: AgentTask):
        data = task.job_data
        input_text = data.get("text", "")
        model_name = data.get("model_name", "aios:qwen3-1-7b-vllm-block")
        session_id = data.get("session_id", str(uuid.uuid4()))
        return input_text, model_name, session_id

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
        self.module = AggregatorModule(self.persona_default_system_message)
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

    def _execute_worker(self, input_text, model_name, session_id):
        with self.model_context.get_context(model_name=model_name, session_id=session_id):
            return self.module(report_json=input_text)

    def on_data(self, task: AgentTask) -> AgentResult:
        try:
            input_text, model_name, session_id = self._prepare_inputs(task)
            log.info("Aggregating final triage summary...")

            # 1. Run DSPy Module
            llm_session_id = str(uuid.uuid4())
            result = self._execute_worker(input_text, model_name, llm_session_id)
            
            # Construct JSON manually for robustness
            t_type = getattr(result, "type", "feature")
            t_title = getattr(result, "title", "Untitled")
            t_summary = getattr(result, "one_line_summary", "")
            t_body = getattr(result, "body_markdown", "")
            t_flags = getattr(result, "quality_flags", "")
            t_code = getattr(result, "final_code", "None")
            
            flags_list = self.parser.to_list(t_flags)

            output_json_str = json.dumps({
                "type": t_type,
                "title": t_title,
                "one_line_summary": t_summary,
                "body_markdown": t_body,
                "quality_flags": flags_list,
                "final_code": t_code
            })
            
            # Attempt to parse final summary for metadata
            metadata = {
                "length": len(output_json_str),
                "final_status": "Completed",
                "quality_flags_count": len(flags_list)
            }

            return AgentResult(
                task_id=task.task_id,
                job_output={"text": output_json_str},
                job_output_metadata=metadata,
                is_error=False,
            )

        except Exception as e:
            log.exception(f"Error in Final Aggregator Agent: {e}")
            return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})

main(SampleAgent)
