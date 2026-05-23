import logging
import uuid
import yaml
import json, random, string
import dspy
from typing import List, Optional

from agents_sdk.core.agent_executor import AgentTask, AgentResult, Context
from agents_sdk.core.main import main
from agents_sdk.core.known_agents import KnownAgents
from agents_search.search import AgentSearchSelector
from utils.dspy_aios_llms import AIOS_DSPy_LMs
from agents_sdk.core.his import HisClient

log = logging.getLogger(__name__)

# --- DSPy Signatures ---
class SoftwareGeneratorSignature(dspy.Signature):
    """
    You are the Software Architect Generator.
    Your goal is to design a complete, high-level software architecture based on the user's requirements.
    Propose a set of discrete components that will make up the system.
    For each component, provide a high-level technical description.
    """
    user_request = dspy.InputField(desc="The initial software requirement from the user")
    reasoning = dspy.OutputField(desc="Your internal reasoning for the proposed architecture")
    architecture_plan = dspy.OutputField(desc="The complete high-level architecture plan")

class ComponentDiscussionSignature(dspy.Signature):
    """
    You are the Software Architecture Generator, currently in refinement mode.
    You will work on one component at a time as directed by the Senior Architect.

    CRITICAL INSTRUCTIONS:
    1. NO PROCRASTINATION: You MUST implement all architectural changes IMMEDIATELY in the `component_details`. Never say "I will add..." or "In the next version...".
    2. TECHNICAL ASSERTIVENESS: Your output must be a professional technical specification. Avoid conversational filler like "I acknowledge your feedback", "You are right", or "Thank you".
    3. CONCRETE SOLUTIONS: Provide specific technical answers. DO NOT say "I will use a distributed database"; say "I will implement a 3-node HA cluster using PostgreSQL with Patroni for failover."
    4. QUANTITATIVE PRECISION: For every component, you MUST provide (or update) these technical estimates:
       - Expected Load (req/sec or concurrent users).
       - Estimated RAM and CPU usage per node.
       - Disk I/O and storage requirements.
       - Network bandwidth and latency expectations.
    5. STAND-ALONE SPEC: `component_details` must always be a complete, self-contained technical specification of this component.
    6. EVOLVE OR DEFEND: If the Architect finds a flaw, you must either PIVOT to a better tool/pattern or provide a firm defense. Never repeat the same plan with more adjectives.
    7. NO ECHO: Never repeat the Architect's feedback, reasoning, or scores in your `component_details`. Start directly with the specification.
    """
    user_request = dspy.InputField(desc="The initial software requirement from the user")
    finalized_components = dspy.InputField(desc="Components already agreed upon and finalized (context)")
    current_component_name = dspy.InputField(desc="The specific component being debated")
    component_history = dspy.InputField(desc="Brief context of previous rounds for this component")
    feedback = dspy.InputField(desc="Specific technical critique or questions from the Senior Architect")

    reasoning = dspy.OutputField(desc="Internal technical trade-offs (e.g., 'Why Choice A over Choice B?'). Do NOT summarize.")
    component_details = dspy.OutputField(desc="The COMPLETELY UPDATED technical specification for this component. No conversational text.")

class SoftwareGeneratorModule(dspy.Module):
    def __init__(self, system_prompt):
        super().__init__()
        self.initial_generator = dspy.ChainOfThought(SoftwareGeneratorSignature.with_instructions(system_prompt))
        self.component_refiner = dspy.ChainOfThought(ComponentDiscussionSignature)

    def forward(self, user_request, finalized_components, current_component_name, component_history, feedback, **kwargs):
        if current_component_name == "Initial Overall Architecture":
            return self.initial_generator(user_request=user_request, **kwargs)
        else:
            return self.component_refiner(
                user_request=user_request,
                finalized_components=finalized_components,
                current_component_name=current_component_name,
                component_history=component_history,
                feedback=feedback,
                **kwargs
            )

class AgentPayloadProcessor:
    def prepare_payload(self, task: AgentTask):
        data = task.job_data
        user_request = data.get("user_request", data.get("text", ""))
        current_component_name = data.get("current_component_name", "Initial Overall Architecture")
        component_history = data.get("component_history", "No history available.")
        finalized_components = data.get("finalized_components", "None yet.")
        feedback = data.get("text", "Initial Request")
        communication_type = data.get("communication_type", "p2p")
        model_name = data.get("model_name", "aios:qwen3-1-7b-vllm-block")
        session_id = data.get("session_id", str(uuid.uuid4()))
        round_count_component = data.get("round_count_component", {})
        round_count = int(data.get("round_count", 0)) + 1
        return user_request, current_component_name, component_history, finalized_components, feedback, communication_type, model_name, session_id, round_count_component, round_count

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

class SoftwareAgent:
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
        self.module = SoftwareGeneratorModule(self.persona_default_system_message)
        self.payload_processor = AgentPayloadProcessor()
        self.model_context = ModelContextManager(self.aios_dspy_lm)

        # Determine next agent (Senior Architect)
        self.next_agent_subject_id = self.agents_config.get("architecture-debate", {}).get("software-agent", {}).get("next_agent")
        if not self.next_agent_subject_id:
            self.next_agent_subject_id = "senior-architect-agent"

        # Initialize HIS Client
        his_config = self.subject.persona.config.get("parameters", {}).get("HIS_CONFIG", {})
        self.his_client = HisClient(
            base_url=his_config["HIS_BASE_URL"],
            poll_interval=his_config.get("HIS_POLL_INTERVAL", 1.0),
            max_wait=his_config.get("HIS_MAX_WAIT", 60)
        )

    def get_muxer(self):
        return None

    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        return [task]

    def on_postprocess(self, task: AgentTask, result: AgentResult) -> AgentResult:
        return result

    def _generate_dummy_session_id(self):
        possible_characters = string.digits
        return "session-"+''.join(random.choice(possible_characters) for _ in range(5))

    def _prepare_inputs(self, task: AgentTask):
        user_request, current_component_name, component_history, finalized_components, feedback, communication_type, model_name, session_id, round_count_component, round_count = self.payload_processor.prepare_payload(task)
        
        # Increment component-specific round count if we are in a component-specific debate
        if current_component_name != "Initial Overall Architecture":
            round_count_component[current_component_name] = round_count_component.get(current_component_name, 0) + 1

        return user_request, current_component_name, component_history, finalized_components, feedback, communication_type, model_name, session_id, round_count_component, round_count

    def _execute_worker(self, user_request, finalized_components, current_component_name, component_history, feedback, model_name):
        attempts = 0
        max_attempts = 3
        result = None

        while attempts < max_attempts:
            attempts += 1
            try:
                dummy_session_id = self._generate_dummy_session_id()
                with self.model_context.get_context(model_name, dummy_session_id):
                    result = self.module(
                        user_request=user_request,
                        finalized_components=finalized_components,
                        current_component_name=current_component_name,
                        component_history=component_history,
                        feedback=feedback,
                        session_id=dummy_session_id
                    )

                # Validation: Check for truncation
                details = getattr(result, 'component_details', getattr(result, 'architecture_plan', ""))
                if not details or len(details) < 50:
                    log.warning(f"Attempt {attempts}: Output too short ({len(details) if details else 0} chars). Rejecting.")
                    continue

                allowed_endings = ('.', '!', '?', '"', "'", '`', '}', 'y', 's', 'B', 'P', 'E', 'z', ')', ']', '*', '-', ':', ';', ',', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9')
                if not details.strip().endswith(allowed_endings):
                    log.warning(f"Attempt {attempts}: Output appears truncated. Rejected content tail: ...{details[-100:]}")
                    continue

                return result
                
            except Exception as e:
                log.error(f"Attempt {attempts}: Error in DSPy prediction: {e}")
                
            if attempts < max_attempts:
                import time
                time.sleep(1)
                
        raise ValueError(f"Failed to generate valid architecture for {current_component_name} after {max_attempts} attempts.")

    def _delegate_task(self, task, proposed_arch, user_request, current_component_name, round_count_component, session_id, model_name, round_count, communication_type):
        payload = {
            "text": proposed_arch,
            "user_request": user_request,
            "current_component_name": current_component_name,
            "round_count_component": round_count_component,
            "session_id": session_id,
            "model_name": model_name,
            "round_count": round_count,
            "communication_type": communication_type
        }
        if communication_type == "p2p":
            self.context.p2p_manager.send_sync(task=task, subject_id=self.next_agent_subject_id, job_data=payload, session_id=session_id)
        else:
            self.context.direct.submit(to=self.next_agent_subject_id, session_id=session_id, task=task, job_data=payload)

    def on_data(self, task: AgentTask) -> AgentResult:
        try:
            user_request, current_component_name, component_history, finalized_components, feedback, communication_type, model_name, session_id, round_count_component, round_count = self._prepare_inputs(task)
            
            log.info(f"--- DEBATE ROUND {round_count} ---")
            log.info(f"Focusing on Component: {current_component_name}")

            # 1. Run DSPy Module
            result = self._execute_worker(user_request, finalized_components, current_component_name, component_history, feedback, model_name)

            proposed_arch = getattr(result, 'component_details', getattr(result, 'architecture_plan', ""))

            log.info(f"Generated plan for {current_component_name}: {proposed_arch[:100]}...")

            # 1.5 Submit to HIS
            try:
                msg = f"Round {round_count} - {current_component_name}\nPlan: {proposed_arch}\nReasoning: {result.reasoning}"
                self.his_client.submit(input_data={"text": msg})
            except: pass

            # 3. Call Senior Architect Agent
            self._delegate_task(task, proposed_arch, user_request, current_component_name, round_count_component, session_id, model_name, round_count, communication_type)

            return AgentResult(task_id=task.task_id, skip=True)

        except Exception as e:
            log.exception(f"Error in Software Agent: {e}")
            return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})

if __name__ == "__main__":
    main(SoftwareAgent)
