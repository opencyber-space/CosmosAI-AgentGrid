import logging
import re
import uuid
import yaml
import json
import dspy
import copy
from typing import List, Optional

from agents_sdk.core.agent_executor import AgentTask, AgentResult, Context
from agents_sdk.core.main import main
from agents_sdk.core.known_agents import KnownAgents
from agents_sdk.core.his import HisClient
from agents_search.search import AgentSearchSelector
from agents_search.custom import OpenAISearchSelector
from utils.dspy_aios_llms import AIOS_DSPy_LMs
from openai import OpenAI
import os

log = logging.getLogger(__name__)

class Muxer:
    def __init__(self, N) -> None:
        self.packets = {}
        self.N = N
        self.taskid_vs_N = {}

    def add(self, key, task: AgentTask):
        log.info(f"Adding task with key {key} to Muxer. task_id: {task.task_id}")

        if key not in self.packets:
            if "mux_size" not in task.job_data:
                self.packets[key] = task
                if self.N==1: #This is for N=1
                    log.info(f"Returning muxed task with key {key} for N=1")
                    returnable = copy.deepcopy(self.packets[key])
                    del self.packets[key]
                    return returnable
                return None
            elif "mux_size" in task.job_data: #then set mux_size to N for this task id
                self.taskid_vs_N[task.task_id] = task.job_data["mux_size"]
                log.info(f"Mux Size set for task with taskid {task.task_id} with value {task.job_data['mux_size']}")
                out = "Mux Size set, waiting for other packets."
                return AgentResult(
                    task_id=task.task_id,
                    job_output={"text": out},
                    job_output_metadata={"length": len(out)},
                    is_error=False,
                )
        else: # if key in self.packets i.e N>1
            #check for delayed mux_size reception
            if "mux_size" in task.job_data: #then set mux_size to N for this task id
                self.taskid_vs_N[task.task_id] = task.job_data["mux_size"]
                if key in self.packets and len(self.packets[key].job_data.get("tasks")) == self.taskid_vs_N[task.task_id]:
                    log.info(f"Returning muxed task with key {key}")
                    returnable = copy.deepcopy(self.packets[key])
                    del self.packets[key]
                    del self.taskid_vs_N[task.task_id]
                    return returnable
                else:
                    out = "Mux Size set, waiting for other packets."
                    return AgentResult(
                        task_id=task.task_id,
                        job_output={"text": out},
                        job_output_metadata={"length": len(out)},
                        is_error=False,
                    )
            
            #mux_size is not in task.job_data
            if "text" in self.packets[key].job_data: #when text is present
                existing_text = self.packets[key].job_data["text"]
                del self.packets[key].job_data["text"]
                if "text" in task.job_data:
                    self.packets[key].job_data["tasks"] = [existing_text, task.job_data["text"]]
            else: #when text is present i.e N>1 i.e key has happened once before and initilized tasks
                self.packets[key].job_data.get("tasks").append(task.job_data.get("text",""))
                
            if task.task_id in self.taskid_vs_N and len(self.packets[key].job_data.get("tasks")) == self.taskid_vs_N[task.task_id]:
                log.info(f"Returning muxed task with key {key}")
                returnable = copy.deepcopy(self.packets[key])
                del self.packets[key]
                del self.taskid_vs_N[task.task_id]
                return returnable
            elif task.task_id in self.taskid_vs_N:
                return None
            elif len(self.packets[key].job_data.get("tasks")) == self.N:
                log.info(f"Returning muxed task with key {key}")
                returnable = copy.deepcopy(self.packets[key])
                del self.packets[key]
                return returnable
                
            return None

# --- DSPy Signatures ---
class aggregatorSignature(dspy.Signature):
    """
    You are the BookMyShow Movie Option Aggregator.
    Your objective is to produce a CLEAN list of ELIGIBLE movie recommendations.

    PRIMARY RULE: EXCLUSION OVERRIDES EVERYTHING
    The 'Excluded Genres' and 'special_instructions' (negative constraints) are the highest priority.
    If a movie belongs to an excluded genre, it MUST be removed from consideraton, even if it is a 'Must-See Movie'.

    CRITICAL INSTRUCTIONS:
    1. EXCLUSION FILTER (STEP 1):
       - Review 'Excluded Genres' and 'special_instructions'.
       - For EVERY item in 'theater_matches', check if its genre is excluded.
       - If excluded, mark it as 'Excluded' in your reasoning and DO NOT add it to 'all_valid_options'.

    2. AVAILABILITY CHECK (STEP 2):
       - For matches not excluded in Step 1, check if they fit entirely within the 'User Availability' windows.
       - If it doesn't fit, mark it as 'Excluded' in reasoning.

    3. CLEAN LIST GENERATION (STEP 3):
       - 'all_valid_options' must contain ONLY the items that passed BOTH Step 1 and Step 2.
       - DO NOT list any movie that you marked as 'Excluded' in your reasoning.

    4. NO MERCY ON EXCLUSIONS: Including an excluded genre in 'all_valid_options' is a critical system failure.

    5. FORMATTING:
       - Each option in 'all_valid_options' MUST correspond EXACTLY to a numbered match from 'theater_matches'.
       - Use numbering (1., 2., etc.) for the final list.
       - Include: Movie Title, GENRE, Theater, Day, Show Time, and Duration.

    6. reasoning: For EVERY numbered match in 'theater_matches', explicitly state: 'Included' or 'Excluded' and the specific reason.
    """
    aggregated_findings = dspy.InputField(desc="The aggregated findings from specialist agents (Calendar, Preferences)")
    theater_matches = dspy.InputField(desc="List of available showtimes at various theaters")
    reasoning = dspy.OutputField(desc="Your step-by-step logic for matching")
    all_valid_options = dspy.OutputField(desc="The exhaustive list of ALL movie options fitting user availability")

class ConfirmationSignature(dspy.Signature):
    """
    You are the Precision Booking Selection Assistant.
    Your task is to identify EXACTLY ONE movie option from 'original_options' that matches the 'user_feedback'.

    CRITICAL INSTRUCTION:
    1. If the user feedback matches an option, return ONLY the full text block for that ONE specific option.
    2. If the user feedback refers to a movie, theater, or time NOT in the list (e.g., "theater_X"), you MUST return: "I'm sorry, '{user_feedback}' does not match any of the available options. Please choose from the list provided."
    3. Do NOT default to any option if there is no match.
    4. Do NOT return multiple options.

    Examples:
    - options: "1. movie1 at theaterA... 2. movie2 at theaterB..." feedback: "movie2" -> Output: "2. movie2 at theaterB..."
    - options: "1. movie1 at theaterA..." feedback: "theater_X" -> Output: "I'm sorry, 'theater_X' does not match any of the available options. Please choose from the list provided."
    - options: "1. movie1... 2. movie2..." feedback: "1" -> Output: "1. movie1 at theaterA..."
    """
    original_options = dspy.InputField(desc="The list of movie options presented to the user")
    user_feedback = dspy.InputField(desc="The specific selection or keyword provided by the user")
    final_selection = dspy.OutputField(desc="The EXACT text block of the SINGLE selected movie option OR a 'no match' message")

class BookMyShowModule(dspy.Module):
    def __init__(self, system_prompt):
        super().__init__()
        self.aggregator = dspy.ChainOfThought(aggregatorSignature.with_instructions(system_prompt))
        self.confirmator = dspy.Predict(ConfirmationSignature)

    def forward(self, aggregated_findings=None, theater_matches=None, original_options=None, user_feedback=None):
        if original_options and user_feedback:
            return self.confirmator(original_options=original_options, user_feedback=user_feedback)
        return self.aggregator(aggregated_findings=aggregated_findings, theater_matches=theater_matches)

class AgentPayloadProcessor:
    def prepare_payload(self, task: AgentTask):
        data = task.job_data
        tasks = data.get("tasks", [])
        if not tasks and "text" in data:
            tasks = [data["text"]]
        model_name = data.get("model_name", "aios:qwen3-1-7b-vllm-block")
        session_id = data.get("session_id", str(uuid.uuid4()))
        return tasks, model_name, session_id

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

class BookMyShowAgent:
    def __init__(self, subject, context: Context):
        self.subject = subject
        self.context = context
        self.persona_default_system_message = self.subject.persona.default_system_message

        # Initialize DSPy
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        self.module = BookMyShowModule(self.persona_default_system_message)
        self.payload_processor = AgentPayloadProcessor()
        self.model_context = ModelContextManager(self.aios_dspy_lm)

        # Dynamic Selection Logic
        INFERENCE_SERVER_REGISTRY_URL = self.subject.persona.config['parameters']['INFERENCE_SERVER_REGISTRY_URL']
        BLOCKS_DB_URL = self.subject.persona.config['parameters']['BLOCKS_DB_URL']
        INFERENCE_SERVER_ID = self.subject.persona.config['parameters']['INFERENCE_SERVER_ID']
        AGENT_SELECTOR_LLM = self.subject.persona.config['parameters']['AGENT_SELECTOR_LLM']
        api_key = None
        if 'api_key' in self.subject.persona.config['parameters']:
            api_key = self.subject.persona.config['parameters']['api_key']
        HIS_BASE_URL = self.subject.persona.config['parameters']['HIS_CONFIG']['HIS_BASE_URL']
        HIS_POLL_INTERVAL = self.subject.persona.config['parameters']['HIS_CONFIG']['HIS_POLL_INTERVAL']
        HIS_MAX_WAIT = self.subject.persona.config['parameters']['HIS_CONFIG']['HIS_MAX_WAIT']

        known_agents = KnownAgents(default_compact=False)
        known_agents.query_and_add(query={
            "metadata.subject_search_tags": "movie-planner"
        })
        self.all_agent_ids = [agent.id for agent in known_agents.list_all()]
        log.info("Known agents for movie-planner: %s", self.all_agent_ids)

        mgr = AgentSearchSelector()
        ##------------------For AIOS LLM Registration ----------------
        # mgr.register_new_selector(
        #     name="default",
        #     model=AGENT_SELECTOR_LLM,
        #     inference_server_id=INFERENCE_SERVER_ID,
        #     aios_url_map={
        #         "inference_server_url": INFERENCE_SERVER_REGISTRY_URL,
        #         "blocks_db_url": BLOCKS_DB_URL,
        #     }
        # )
        ##---------------------------------------------
        selector = None
        if "openai:" in AGENT_SELECTOR_LLM:
            model_name = AGENT_SELECTOR_LLM.replace("openai:", "")
            
            selector = OpenAISearchSelector(
                model=model_name,
                client=OpenAI(api_key=api_key)
            )
        if selector:
            mgr.register_custom_selector(
                name="default",
                selector=selector
            )

            chosen_id = mgr.search_from_objects(
                name="default",
                objects=known_agents.list_all(),
                query="For movie theater showtime aggregation and booking",
            )
            self.chosen_agent_id = chosen_id
            log.info("Chosen ID: %s", self.chosen_agent_id)

        self.his_client = HisClient(
            base_url=HIS_BASE_URL,
            poll_interval=HIS_POLL_INTERVAL,
            max_wait=HIS_MAX_WAIT,
        )

        self.muxer = None
        try:
            log.info(f"Initializing Muxer with subject parameters: {self.subject.persona.config['parameters']}")
            self.muxer = Muxer(N=self.subject.persona.config["parameters"]["mux_size"])
        except Exception as e:
            log.warning("Error initializing Muxer with subject parameters, defaulting to 1: %s", e)
            self.muxer = Muxer(N=1)

    def get_muxer(self):
        return self.muxer

    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        if isinstance(task, AgentResult):
            return [task]
        log.info(f"Preprocessing task {task.task_id} {task.job_data}")
        return [task]

    def _clean_output(self, text: str) -> str:
        """Strips DSPy structural markers from the output text using regex."""
        if not text:
            return ""
        # Remove DSPy structural markers like [[ ## field_name ## ]]
        cleaned = re.sub(r'\[\[\s*##.*?##\s*\]\]', '', text)
        # Remove any stray field headers like ## field_name ## if they aren't inside [[ ]]
        # This version is more robust by matching any field name between ##
        cleaned = re.sub(r'##\s*[\w_]+\s*##', '', cleaned, flags=re.IGNORECASE)
        return cleaned.strip()

    def _prepare_inputs(self, task: AgentTask):
        tasks, model_name, session_id = self.payload_processor.prepare_payload(task)

        calendar_slots = []
        preferences = {}
        specialist_findings = []

        for entry in tasks:
            try:
                # Attempt to parse as JSON if specialist agent packed it
                data = json.loads(entry)
                if isinstance(data, dict):
                    calendar_slots = data.get("calendar_slots", calendar_slots)
                    preferences = data.get("movie_preferences", preferences)
                    specialist_findings.append(data.get("findings", ""))
                else:
                    specialist_findings.append(str(entry))
            except (json.JSONDecodeError, TypeError):
                # Fallback for plain text
                specialist_findings.append(str(entry))

        aggregated_findings_text = "\n".join(specialist_findings)
        return aggregated_findings_text, calendar_slots, preferences, model_name, session_id

    def _match_theaters(self, calendar_slots, preferences):
        # Simulate matching with theater availability
        try:
            with open("movie_availability.yaml", "r") as f:
                availability = yaml.safe_load(f)
        except:
            availability = {"theaters": []}

        def to_min(t_str):
            h, m = map(int, t_str.split(':'))
            return h * 60 + m

        matches = []
        for theater in availability.get("theaters", []):
            for movie in theater.get("movies", []):
                # For simulation, simple match on must_see
                if movie["title"] in preferences.get("must_see", []):
                    duration = int(movie.get("duration", 120))
                    for showtime in movie.get("showtimes", []):
                        m_start = to_min(showtime)
                        m_end = m_start + duration

                        for slot in calendar_slots:
                            s_day = slot.get("day", "N/A")
                            s_start = to_min(slot["start"])
                            s_end = to_min(slot["end"])
                            if s_end <= s_start: # Midnight crossing
                                s_end += 1440

                            # Check if movie fits in this slot
                            if m_start >= s_start and m_end <= s_end:
                                matches.append({
                                    "theater": theater["name"],
                                    "movie": movie["title"],
                                    "genre": movie.get("genre", "Unknown"),
                                    "time": showtime,
                                    "duration": duration,
                                    "day": s_day
                                })
                                break
                            if (m_start + 1440) >= s_start and (m_end + 1440) <= s_end:
                                matches.append({
                                    "theater": theater["name"],
                                    "movie": movie["title"],
                                    "genre": movie.get("genre", "Unknown"),
                                    "time": showtime,
                                    "duration": duration,
                                    "day": s_day
                                })
                                break

        # Format matches for LLM with unique IDs
        formatted_matches = []
        for i, m in enumerate(matches, 1):
            end_min = to_min(m["time"]) + m["duration"]
            end_h = (end_min // 60) % 24
            end_m = end_min % 60
            formatted_matches.append(
                f"{i}. {m['movie']} ({m['genre']}) at {m['theater']}, Day: {m['day']}, "
                f"Time: {m['time']} - {end_h:02d}:{end_m:02d} (Duration: {m['duration']} mins)"
            )
        
        matches_text = "\n".join(formatted_matches)
        return matches_text, matches

    def _execute_worker(self, aggregated_findings_text, matches_text, model_name, session_id):
        with self.model_context.get_context(model_name, session_id):
            return self.module(
                aggregated_findings=aggregated_findings_text,
                theater_matches=matches_text
            )

    def _execute_human_feedback(self, final_list, user_choice_raw, model_name, session_id):
        with self.model_context.get_context(model_name, session_id):
            return self.module(
                original_options=final_list,
                user_feedback=str(user_choice_raw)
            )

    def on_data(self, task: AgentTask) -> AgentResult:
        if isinstance(task, AgentResult):
            return task
        try:
            aggregated_findings_text, calendar_slots, preferences, model_name, session_id = self._prepare_inputs(task)
            log.info(f"[{self.chosen_agent_id}] Aggregating data from specialist agents...")

            matches_text, matches = self._match_theaters(calendar_slots, preferences)

            result = self._execute_worker(aggregated_findings_text, matches_text, model_name, session_id)
            log.info(f"Worker result: {result}")
            final_list_raw = self._clean_output(result.all_valid_options)
            reasoning = self._clean_output(result.reasoning)
            log.info(f"Final list raw: {final_list_raw}")
            log.info(f"Reasoning: {reasoning}")

            # Programmatic safety net
            excluded_genres = [g.strip().lower() for g in re.findall(r'Excluded Genres:\s*(.*)', aggregated_findings_text)]
            if "thriller" in aggregated_findings_text.lower() and "exclude" in aggregated_findings_text.lower():
                excluded_genres.append("thriller")

            final_list = "\n".join([line for line in final_list_raw.split('\n') if not any(g and g in line.lower() for g in excluded_genres) and line.strip()])

            log.info(f"[{self.chosen_agent_id}] Generated clean list, waiting for HIS input...")
            log.info(f"Final list: {final_list}")
            log.info(f"Reasoning/Analysis: {reasoning}")
            
            # Send to HIS
            try:
                obj = self.his_client.submit_and_wait(
                    input_data={
                        "task": "Choose Your Movie Option",
                        "text": final_list,
                        "Analysis": reasoning
                    }
                )
                user_choice_raw = obj.response_data.get("user_choice", "")
            except Exception as e:
                log.error(f"Error communicating with HIS: {e}")
                user_choice_raw = "None"
                
            confirmation = self._execute_human_feedback(final_list, user_choice_raw, model_name, session_id)
            
            final_selection = self._clean_output(confirmation.final_selection)
            
            return AgentResult(
                task_id=task.task_id,
                job_output={"text": final_selection},
                job_output_metadata={"length": len(final_selection)},
                is_error=False
            )
        except Exception as e:
            log.error(f"Error processing task {task.task_id}: {e}", exc_info=True)
            return AgentResult(
                task_id=task.task_id,
                job_output={"text": str(e)},
                job_output_metadata={"length": len(str(e))},
                is_error=True
            )

if __name__ == "__main__":
    main(BookMyShowAgent)
