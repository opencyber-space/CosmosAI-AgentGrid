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

log = logging.getLogger(__name__)

# --- DSPy Signatures ---
class CalendarSignature(dspy.Signature):
    """
    You are a Movie Calendar Specialist.
    Determine the best movie slots based on user availability and historical preferences.
    
    RULES:
    1. If the 'original_query' contains specific days (e.g., "Monday and Tuesday"), YOU MUST return ALL free slots for those days from 'calendar_data'.
    2. If 'original_query' is vague (e.g., "I want to watch a movie"), use 'calendar_preferences' to identify the "most likely" DAYS (plural if appropriate) and time windows.
    3. SOURCE HIERARCHY:
       - PRIMARY SOURCE (Slots): 'calendar_data'. ONLY use time ranges from here in the final output.
       - SECONDARY SOURCE (Guidance): 'calendar_preferences'. Use ONLY to select WHICH slots from the Primary Source to include.
    4. INTERSECTION CALCULATION: Your output time ranges MUST be the exact intersection between the preferred window and the actual free slot. 
       - Result Start: The LATER of (Preferred Start Time, Calendar Slot Start Time).
       - Result End: The EARLIER of (Preferred End Time, Calendar Slot End Time).
    5. STEP-BY-STEP LOGIC:
       - Identify preferred windows from 'calendar_preferences'.
       - Find candidate slots in 'calendar_data'.
       - For each candidate, IF it has NO overlap with a preferred window, discard it. IF overlap exists, return the LATER of the starts and EARLIER of the ends.
    6. EXPLICIT FORBIDDANCE: NEVER use specific movie durations or past showtimes from the 'history' section to define output boundaries.
    7. CONCEPTUAL EXAMPLES:
       - Scenario: Preference "After h_pref_start". Calendar slot "h_slot_start to h_slot_end". 
       - Logic: If h_pref_start is later than h_slot_start, the resulting start is h_pref_start. The resulting end remains h_slot_end.
       - Result: "h_pref_start to h_slot_end".
    8. MULTIPLE SLOTS/DAYS: If multiple slots or days match, YOU MUST return them ALL. Format 'formatted_availability' as a clear summary (e.g., "Friday: h_start1-h_end1 | Saturday: h_start2-h_end2").
    9. 'chosen_days' MUST be a comma-separated list of day names (e.g., "friday, saturday").
    10. 'refined_slots_json' MUST be a JSON-formatted list of objects representing the final intersected time ranges (e.g., [{"day": "friday", "start": "h_start", "end": "h_end"}]). 
    """
    query = dspy.InputField(desc="Focused instruction for calendar check")
    original_query = dspy.InputField(desc="The raw user request context")
    calendar_data = dspy.InputField(desc="Raw free slots for the week")
    calendar_preferences = dspy.InputField(desc="User's historical movie-watching patterns and habits")
    chosen_days = dspy.OutputField(desc="Comma-separated list of days resolved for movie night (e.g., 'friday, saturday')")
    formatted_availability = dspy.OutputField(desc="A summary including the days and ALL matching slots")
    refined_slots_json = dspy.OutputField(desc="JSON list of selected free slots from calendar_data")

class CalendarModule(dspy.Module):
    def __init__(self, system_prompt):
        super().__init__()
        self.worker = dspy.ChainOfThought(CalendarSignature.with_instructions(system_prompt))

    def forward(self, query, original_query, calendar_data, calendar_preferences):
        return self.worker(
            query=query, 
            original_query=original_query, 
            calendar_data=calendar_data, 
            calendar_preferences=calendar_preferences
        )

class AgentPayloadProcessor:
    def prepare_payload(self, task: AgentTask):
        data = task.job_data
        input_text = data.get("text", "") # Instruction from planner
        original_query = data.get("original_query", input_text)
        communication_type = data.get("communication_type", "p2p")
        model_name = data.get("model_name", "aios:qwen3-1-7b-vllm-block")
        session_id = data.get("session_id", "")
        return input_text, original_query, communication_type, model_name, session_id

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

class MovieCalendarAgent:
    def __init__(self, subject, context:Context):
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

        # Initialize DSPy
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        self.module = CalendarModule(self.persona_default_system_message)
        self.payload_processor = AgentPayloadProcessor()
        self.model_context = ModelContextManager(self.aios_dspy_lm)

        # Dynamic Selection Logic
        INFERENCE_SERVER_REGISTRY_URL = self.subject.persona.config['parameters']['INFERENCE_SERVER_REGISTRY_URL']
        BLOCKS_DB_URL = self.subject.persona.config['parameters']['BLOCKS_DB_URL']
        INFERENCE_SERVER_ID = self.subject.persona.config['parameters']['INFERENCE_SERVER_ID']
        AGENT_SELECTOR_LLM = self.subject.persona.config['parameters']['AGENT_SELECTOR_LLM']

        known_agents = KnownAgents(default_compact=False)
        known_agents.query_and_add(query={
            "metadata.subject_search_tags": "movie-planner"
        })
        self.all_agent_ids = [agent.id for agent in known_agents.list_all()]
        log.info("Known agents for movie-planner: %s", self.all_agent_ids)

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
            query="For checking user schedule and calendar availability",
        )
        self.chosen_agent_id = chosen_id
        log.info("Chosen ID: %s", self.chosen_agent_id)

    def get_muxer(self):
        return None

    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        return [task]

    def _prepare_inputs(self, task: AgentTask):
        input_text, original_query, communication_type, model_name, session_id = self.payload_processor.prepare_payload(task)
        
        # Simulate calendar and preference lookup
        try:
            with open("movie_calendar.yaml", "r") as f:
                raw_calendar = yaml.safe_load(f)
        except:
            raw_calendar = {}

        try:
            with open("calendar_preference.yaml", "r") as f:
                calendar_prefs = yaml.safe_load(f)
        except:
            calendar_prefs = {}

        return input_text, original_query, communication_type, model_name, session_id, raw_calendar, calendar_prefs

    def _execute_worker(self, input_text, original_query, model_name, session_id, raw_calendar, calendar_prefs):
        with self.model_context.get_context(model_name, session_id):
            return self.module(
                query=input_text, 
                original_query=original_query,
                calendar_data=str(raw_calendar),
                calendar_preferences=str(calendar_prefs)
            )

    def on_data(self, task: AgentTask) -> AgentResult:
        try:
            input_text, original_query, communication_type, model_name, session_id, raw_calendar, calendar_prefs = self._prepare_inputs(task)

            log.info(f"[{self.chosen_agent_id}] Retrieving calendar slots and preferences...")

            result = self._execute_worker(input_text, original_query, model_name, session_id, raw_calendar, calendar_prefs)
            
            chosen_days_str = result.chosen_days.lower().strip()
            # Handle list-like strings or comma-separated values
            chosen_days = [d.strip() for d in chosen_days_str.replace('[','').replace(']','').replace("'",'').replace('"','').split(',')]
            
            log.info(f"Chosen Days: {chosen_days}")
            log.info(f"Formatted Availability: {result.formatted_availability}")
            log.info(f"Refined Slots JSON: {result.refined_slots_json}")

            # 3. Communication Pipeline
            # Parse the refined JSON from the LLM instead of using raw slots
            try:
                refined_slots = json.loads(result.refined_slots_json)
                if not isinstance(refined_slots, list):
                    refined_slots = []
            except Exception as e:
                log.error(f"Failed to parse refined_slots_json: {e}. Falling back to empty.")
                refined_slots = []
            
            packed_payload = {
                "findings": result.formatted_availability,
                "calendar_slots": refined_slots,
                "formatted_availability": result.formatted_availability
            }
            
            payload = {
                "text": json.dumps(packed_payload),
            }

            next_agent_subject_id = self.agents_config.get("movie-booking", {}).get(self.chosen_agent_id, {}).get("next_agent")
            
            if not next_agent_subject_id:
                log.warning(f"No next agent configured for {self.chosen_agent_id}")
                return AgentResult(task_id=task.task_id, job_output=payload)

            log.info(f"Preparing to call next agent: {next_agent_subject_id} with communication type: {communication_type}")
            
            new_session_id = str(uuid.uuid4())
            if communication_type == "p2p":
                self.context.p2p_manager.send_sync(
                    task=task, subject_id=next_agent_subject_id,
                    job_data={
                        **payload,
                        "session_id": new_session_id,
                        "model_name": model_name,
                        "communication_type": communication_type
                    }, 
                    session_id=new_session_id
                )
            else:
                self.context.direct.submit(to=next_agent_subject_id, session_id=new_session_id, task=task, job_data={
                    **payload,
                    "session_id": new_session_id,
                    "model_name": model_name,
                    "communication_type": communication_type
                })

            return AgentResult(task_id=task.task_id, skip=True)

        except Exception as e:
            log.exception(f"Error in Movie Calendar: {e}")
            return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})

if __name__ == "__main__":
    main(MovieCalendarAgent)
