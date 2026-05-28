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
from agents_search.custom import OpenAISearchSelector,GeminiSearchSelector
from utils.dspy_aios_llms import AIOS_DSPy_LMs
from openai import OpenAI
import os

log = logging.getLogger(__name__)

# --- DSPy Signatures ---
class PlannerSignature(dspy.Signature):
    """
    You are a Movie Planner Orchestrator. 
    Analyze the user's request and identify which information is needed.
    Typically, you need to check both the user's schedule (Calendar) and their movie tastes (Preferences).
    """
    text = dspy.InputField(desc="The user's request")
    plan = dspy.OutputField(desc="A brief plan of action")
    calendar_query = dspy.OutputField(desc="Specific instruction for the Calendar Agent to check availability")
    preference_query = dspy.OutputField(desc="Specific instruction for the Preference Agent to check user tastes")

class PlannerModule(dspy.Module):
    def __init__(self, system_prompt):
        super().__init__()
        self.planner = dspy.ChainOfThought(PlannerSignature.with_instructions(system_prompt))

    def forward(self, text):
        return self.planner(text=text)

class AgentPayloadProcessor:
    def prepare_payload(self, task: AgentTask):
        data = task.job_data
        text = data.get("text", "")
        communication_type = data.get("communication_type", "p2p")
        model_name = data.get("model_name", "aios:qwen3-1-7b-vllm-block")
        session_id = data.get("session_id", "")
        return text, communication_type, model_name, session_id

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

class MoviePlannerAgent:
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

        # Initialize DSPy
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        self.module = PlannerModule(self.persona_default_system_message)
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
            from openai import OpenAI
            selector = OpenAISearchSelector(
                model=model_name,
                client=OpenAI(api_key=api_key)
            )
        elif "gemini:" in AGENT_SELECTOR_LLM or "google:" in AGENT_SELECTOR_LLM:
            model_name = AGENT_SELECTOR_LLM.replace("gemini:", "").replace("google:", "")
            from google import genai
            selector = GeminiSearchSelector(
                model=model_name,
                client= genai.Client(api_key=api_key)
            )
        elif "aios:" in AGENT_SELECTOR_LLM:
            model_name = AGENT_SELECTOR_LLM.replace("aios:", "")
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
                query="For movie planning and task delegation",
            )
            self.chosen_agent_id = chosen_id
            log.info("Chosen ID: %s", self.chosen_agent_id)
        if selector:
            mgr.register_custom_selector(
                name="default",
                selector=selector
            )

            chosen_id = mgr.search_from_objects(
                name="default",
                objects=known_agents.list_all(),
                query="For movie planning and task delegation",
            )
            self.chosen_agent_id = chosen_id
            log.info("Chosen ID: %s", self.chosen_agent_id)
    
    def get_muxer(self):
        return None

    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        return [task]

    def update_mux_size_to_aggregator(self, task: AgentTask, communication_type: str, model_name: str):
        # Based on agents_config.yaml: movie-booking -> movieplanner-planner-agent -> [movieplanner-calendar-agent, movieplanner-preferences-agent]
        # And BookMyShow is the aggregator
        next_agent_subject_id_list = self.agents_config.get("movie-booking", {}).get("movieplanner-planner-agent", {}).get("next_agent", [])
        aggregator_agent_id = "movieplanner-bookmyshow-agent" # Explicit aggregator for this flow

        # send mux_size in job_data to synthesizer agent mux so that mux will wait only for those many inputs
        synthesizer_mux_size = len(next_agent_subject_id_list)
        next_agent_subject_id = aggregator_agent_id
        
        log.info(f"Preparing to call aggregator: {next_agent_subject_id} with mux_size={synthesizer_mux_size}")

        session_id = str(uuid.uuid4())
        if communication_type == "delegate":
            self.context.delegator.submit_and_wait(
                subject_id=next_agent_subject_id, session_id=session_id,
                task_id=task.task_id, task_data={
                    "mux_size": synthesizer_mux_size,
                    "session_id": session_id,
                    "model_name": model_name,
                    "communication_type": communication_type
                }
            )
        elif communication_type == "p2p":
            self.context.p2p_manager.send_and_wait_sync(
                task.task_id, subject_id=next_agent_subject_id,
                task_data={
                    "mux_size": synthesizer_mux_size,
                    "session_id": session_id,
                    "model_name": model_name,
                    "communication_type": communication_type
                }
            )
        else:
            self.context.delegator.submit_and_wait(
                subject_id=next_agent_subject_id, session_id=session_id,
                task_id=task.task_id, task_data={
                    "mux_size": synthesizer_mux_size,
                    "session_id": session_id,
                    "model_name": model_name,
                    "communication_type": communication_type
                }
            )

    def _prepare_inputs(self, task: AgentTask):
        return self.payload_processor.prepare_payload(task)

    def _execute_worker(self, text, model_name, session_id):
        with self.model_context.get_context(model_name, session_id):
            return self.module.forward(text=text)

    def _delegate_tasks(self, task, text, result, communication_type, model_name):
        # Call specialized agents with curated instructions
        next_agent_subject_id_list = self.agents_config.get("movie-booking", {}).get("movieplanner-planner-agent", {}).get("next_agent", [])
        
        for next_agent_id in next_agent_subject_id_list:
            log.info(f"Triggering specialist agent: {next_agent_id}")
            
            # Curate input based on agent type
            if "calendar" in next_agent_id:
                instruction = result.calendar_query
            elif "preference" in next_agent_id:
                instruction = result.preference_query
            else:
                instruction = text

            session_id = str(uuid.uuid4())
            if communication_type == "p2p":
                self.context.p2p_manager.send_sync(
                    task=task, subject_id=next_agent_id,
                    job_data={
                        "text": instruction,
                        "original_query": text,
                        "session_id": session_id,
                        "model_name": model_name,
                        "communication_type": communication_type
                    }, 
                    session_id=session_id
                )
            else:
                self.context.direct.submit(to=next_agent_id, session_id=session_id, task=task, job_data={
                    "text": instruction,
                    "original_query": text,
                    "session_id": session_id,
                    "model_name": model_name,
                    "communication_type": communication_type
                })

    def on_data(self, task: AgentTask) -> AgentResult:
        try:
            text, communication_type, model_name, session_id = self._prepare_inputs(task)
            log.info(f"[{self.chosen_agent_id}] Processing user request: {text}")

            result = self._execute_worker(text, model_name, session_id)
            log.info(f"DSPy Plan: {result.plan}")

            self.update_mux_size_to_aggregator(task, communication_type, model_name)
            self._delegate_tasks(task, text, result, communication_type, model_name)

            return AgentResult(task_id=task.task_id, skip=True)

        except Exception as e:
            log.exception(f"Error in Movie Planner: {e}")
            return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})

if __name__ == "__main__":
    main(MoviePlannerAgent)
