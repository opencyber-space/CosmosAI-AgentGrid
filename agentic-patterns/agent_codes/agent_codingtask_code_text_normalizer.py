import logging, json, yaml, os, uuid, random, string
from typing import List, Optional
import dspy

from agents_sdk.core.agent_executor import AgentTask, AgentResult
from agents_sdk.core.main import main
from agents_sdk.core.agent_executor import Context
from utils.dspy_aios_llms import AIOS_DSPy_LMs, clean_json_string
from utils.condition import route, RouteResult

log = logging.getLogger(__name__)

# --- DSPy Signatures ---
class NormalizerSignature(dspy.Signature):
    """
    You are Agent1, a expert draft normalizer. Normalize the user’s short draft without adding or removing facts.
    Tasks:
    1) fix obvious casing and spacing
    2) correct glaring typos without changing intent
    3) expand common infra abbreviations when unambiguous (cfg->config, svc->service, req->request)
    4) keep original meaning and uncertainty
    5) do not invent steps, logs, or metrics.
    6) CRITICAL: You must preserve any "note:" or "instruction:" sections exactly as they are. These are vital for downstream routing. If the user mentions "bug" or "fix", ensure this intent is carried forward.

    Keep normalized text under 1200 characters.
    
    Output fields:
    1) normalized_text: The normalized version of the raw input
    2) char_count: Number of characters in normalized text
    3) word_count: Number of words in normalized text
    """
    text = dspy.InputField(desc="The raw text or code to be normalized")
    normalized_text = dspy.OutputField(desc="The normalized version of the input text")
    char_count = dspy.OutputField(desc="Number of characters in the normalized text")
    word_count = dspy.OutputField(desc="Number of words in the normalized text")

# --- DSPy Modules ---
class NormalizerModule(dspy.Module):
    def __init__(self, system_prompt):
        super().__init__()
        self.predict = dspy.Predict(NormalizerSignature.with_instructions(system_prompt))

    def forward(self, text):
        return self.predict(text=text)

class AgentPayloadProcessor:
    def prepare_payload(self, task: AgentTask):
        data = task.job_data
        text = data.get("text", "")
        session_id = data.get("session_id", "")
        communication_type = data.get("communication_type", "delegate")
        
        if not session_id:
            possible_characters = string.digits
            session_id = "session-"+"".join(random.choice(possible_characters) for _ in range(5))
            log.warning(f"No session_id in job_data, generated new one: {session_id}")
            
        model_name = data.get("model_name", "aios:qwen3-1-7b-vllm-block")
        return text, session_id, communication_type, model_name

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
        self.module = NormalizerModule(self.persona_default_system_message)
        self.payload_processor = AgentPayloadProcessor()
        self.model_context = ModelContextManager(self.aios_dspy_lm)

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

    def _execute_worker(self, text, model_name, session_id):
        with self.model_context.get_context(model_name=model_name, session_id=session_id):
            return self.module(text=text)

    def on_data(self, task: AgentTask) -> AgentResult:
        try:
            input_text, session_id, communication_type, model_name = self._prepare_inputs(task)
            log.info("Using session_id: %s", session_id)

            # 1. Run DSPy Module
            llm_session_id = str(uuid.uuid4())
            result = self._execute_worker(input_text, model_name, llm_session_id)
            
            # Construct JSON manually from fields for robustness
            normalized_text = getattr(result, "normalized_text", input_text)
            try:
                char_c = int(getattr(result, "char_count", len(normalized_text)))
            except:
                char_c = len(normalized_text)
            try:
                word_c = int(getattr(result, "word_count", len(normalized_text.split())))
            except:
                word_c = len(normalized_text.split())
                
            output_json_str = json.dumps({
                "normalized_text": normalized_text,
                "quick_stats": {
                    "chars": char_c,
                    "words": word_c
                }
            })
            
            log.info(f"Normalized Text: {normalized_text[:100]}...")
            
            # 2. Implement condition/routing
            r = route(normalized_text)
            
            # Fallback check: if no strong signals in normalized text, check original input
            if r.reasons == ["no strong signals"]:
                log.info("No strong signals in normalized text, falling back to original input text for routing.")
                r_fallback = route(input_text)
                if r_fallback.route == "bug" or r_fallback.reasons != ["no strong signals"]:
                    log.info(f"Fallback routing found signal: {r_fallback.route} based on {r_fallback.reasons}")
                r = r_fallback

            log.info(f"Final routing decision: {r.route} based on reasons: {r.reasons}")

            # Map route to specific agent IDs from agents_config if possible, or use hardcoded logic
            next_agent_subject_id = "feature-improver-agent"
            if r.route == "bug":
                next_agent_subject_id = "bug-fixer-agent"
                
            # 3. Package state for next agent
            state = {
                "input_text": input_text,
                "normalized_text": normalized_text,
                "route_decision": r.route,
                "route_reasons": r.reasons
            }
            
            input_to_next_agent = json.dumps(state)
            
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

            # if delegate_json and "data" in delegate_json::
            #    out = delegate_json.get("data", {}).get("reply","")
            # return AgentResult(
            #     task_id=task.task_id,
            #     job_output={"text": out},
            #     job_output_metadata={"length": len(out)},
            #     is_error=False,
            # )
            return AgentResult(
                task_id=task.task_id,
                job_output=op_x,
                job_output_metadata={"length": len(input_to_next_agent)},
                is_error=False,
            )

            # else:
            
            #    return AgentResult(
            #        task_id=task.task_id,
            #        job_output={"text": out},
            #        job_output_metadata={"length": len(out)},
            #        is_error=False,
            #    )
            
        except Exception as e:
            log.exception(f"Error in Code Text Normalizer: {e}")
            return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})

if __name__ == "__main__":
    main(SampleAgent)
