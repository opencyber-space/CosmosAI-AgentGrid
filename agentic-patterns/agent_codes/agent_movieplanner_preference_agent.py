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
from agents_search.custom import OpenAISearchSelector
from utils.dspy_aios_llms import AIOS_DSPy_LMs
from openai import OpenAI
import os

log = logging.getLogger(__name__)

# --- DSPy Signatures ---
class PreferenceSignature(dspy.Signature):
    """
    You are a Movie Preference Specialist.
    Analyze the user's movie tastes, recently watched history, and special instructions.
    
    RULES:
    1. EXCLUSIONS: If 'watched_history' or 'special_instructions' imply a genre should be avoided (e.g., "watched thriller last week"), explicitly list it in 'Excluded Genres'.
    2. STRUCTURE: Your summary MUST include:
       - Must-See Movies
       - Excluded Genres (highly specific)
       - Preferred Genres
       - Special Logic (e.g., "Exclude Thriller due to recent history")
    """
    query = dspy.InputField(desc="The specific request for user movie preferences")
    preference_data = dspy.InputField(desc="Raw static user preferences")
    watched_history = dspy.InputField(desc="History of recently watched movies and their genres")
    special_instructions = dspy.InputField(desc="Complex rules or negative constraints")
    preferences_summary = dspy.OutputField(desc="A structured summary including exclusions and rules for the aggregator")

class PreferenceModule(dspy.Module):
    def __init__(self, system_prompt):
        super().__init__()
        self.worker = dspy.ChainOfThought(PreferenceSignature.with_instructions(system_prompt))

    def forward(self, query, preference_data, watched_history, special_instructions):
        return self.worker(
            query=query, 
            preference_data=preference_data, 
            watched_history=watched_history, 
            special_instructions=special_instructions
        )

class AgentPayloadProcessor:
    def prepare_payload(self, task: AgentTask):
        data = task.job_data
        input_text = data.get("text", "")
        communication_type = data.get("communication_type", "p2p")
        model_name = data.get("model_name", "aios:qwen3-1-7b-vllm-block")
        session_id = data.get("session_id", "")
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

class MoviePreferenceAgent:
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
        self.module = PreferenceModule(self.persona_default_system_message)
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
                query="For identifying user movie tastes and preferences",
            )
            self.chosen_agent_id = chosen_id
            log.info("Chosen ID: %s", self.chosen_agent_id)

    def get_muxer(self):
        return None

    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        return [task]

    def _prepare_inputs(self, task: AgentTask):
        input_text, communication_type, model_name, session_id = self.payload_processor.prepare_payload(task)
        
        # Simulate preference and history lookup
        try:
            with open("movie_preferences.yaml", "r") as f:
                raw_prefs = yaml.safe_load(f)
        except:
            raw_prefs = {"preferences": {"genres": [], "must_see": []}}

        try:
            with open("movie_history_watched.yaml", "r") as f:
                history_data = yaml.safe_load(f)
                watched_history = history_data.get("history", [])
                special_instructions = history_data.get("special_instructions", [])
        except:
            watched_history = []
            special_instructions = []

        return input_text, communication_type, model_name, session_id, raw_prefs, watched_history, special_instructions

    def _execute_worker(self, input_text, model_name, session_id, raw_prefs, watched_history, special_instructions):
        with self.model_context.get_context(model_name, session_id):
            return self.module.forward(
                query=input_text, 
                preference_data=str(raw_prefs),
                watched_history=str(watched_history),
                special_instructions=str(special_instructions)
            )

    def on_data(self, task: AgentTask) -> AgentResult:
        try:
            input_text, communication_type, model_name, session_id, raw_prefs, watched_history, special_instructions = self._prepare_inputs(task)

            log.info(f"[{self.chosen_agent_id}] Retrieving user preferences and history...")

            result = self._execute_worker(input_text, model_name, session_id, raw_prefs, watched_history, special_instructions)
            
            log.info(f"Preferences Summary: {result.preferences_summary}")

            # 3. Communication Pipeline
            packed_payload = {
                "findings": result.preferences_summary,
                "movie_preferences": raw_prefs.get("preferences", {}),
                "formatted_preferences": result.preferences_summary
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
            log.exception(f"Error in Movie Preferences: {e}")
            return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})

if __name__ == "__main__":
    main(MoviePreferenceAgent)
