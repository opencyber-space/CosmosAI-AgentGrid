import logging
import uuid
import yaml
import json
import dspy
import os,random,string
from typing import List, Optional
from datetime import datetime

from agents_sdk.core.agent_executor import AgentTask, AgentResult, Context
from agents_sdk.core.main import main
from agents_sdk.core.known_agents import KnownAgents
from utils.dspy_aios_llms import AIOS_DSPy_LMs
from agents_sdk.core.his import HisClient

log = logging.getLogger(__name__)

# --- DSPy Signatures ---
class ComponentParserSignature(dspy.Signature):
    """
    Parse a software architecture proposal into discrete, named components and their descriptions.
    Output MUST be a valid JSON dictionary where:
    - Keys are the component names.
    - Values are the detailed descriptions or implementation plans for those components as provided in the proposal.
    """
    proposed_architecture = dspy.InputField(desc="The full architecture plan from the Software Agent")
    components_map_json = dspy.OutputField(desc="A JSON dictionary of {component_name: description}")

class ComponentEvaluatorSignature(dspy.Signature):
    """
    You are the Senior Solutions Architect.
    Evaluate a SPECIFIC component of the software architecture proposed by the Software Agent.
    
    QUANTITATIVE SCRUTINY:
    - Mathematically evaluate the proposed design:
      - Is the Load prediction realistic for the user's request?
      - Are the RAM, CPU, and Disk estimates sufficient or overkill?
      - Will the proposed architecture meet the required Network Bandwidth and Latency targets?
    
    CREATIVE PROBING:
    - Don't just check requirement compliance.
    - Ask "CRAZY" questions: "What if the DB node vanishes?", "What if network latency spikes to 500ms?", "What if a rogue consumer deletes all data?"
    - Your goal is to break the design to ensure it's bulletproof.
    - Assign a 'satisfaction_score' (0-100).
    - Only approve if description is technically flawless and satisfaction_score >= 95.
    """
    user_request = dspy.InputField(desc="The initial software requirement")
    finalized_component_names = dspy.InputField(desc="List of names of components already agreed upon (context only)")
    current_component_name = dspy.InputField(desc="The name of the component being debated")
    current_component_details = dspy.InputField(desc="Details/Plan for this component from the Software Agent")
    
    is_approved = dspy.OutputField(desc="True if satisfaction_score >= 95", type=bool)
    satisfaction_score = dspy.OutputField(desc="Score 0-100 reflecting confidence in the component's robustness.")
    feedback = dspy.OutputField(desc="Critical probing questions about failure modes (e.g., 'What if X fails?'). Required if score < 95.")
    reasoning = dspy.OutputField(desc="Explanation of the score: why convinced (80%) and why not (20%).")

class FinalSynthesisSignature(dspy.Signature):
    """
    Consolidate all finalized components into a complete, professional architecture report.
    Describe each component's role in satisfying the user request.
    """
    user_request = dspy.InputField(desc="The initial requirement")
    finalized_components = dspy.InputField(desc="The full list of agreed components and their details")
    final_architecture_report = dspy.OutputField(desc="The final synthesized report for the user")

class ArchitectEvaluatorModule(dspy.Module):
    def __init__(self, system_prompt):
        super().__init__()
        self.parser = dspy.Predict(ComponentParserSignature)
        self.evaluator = dspy.ChainOfThought(ComponentEvaluatorSignature.with_instructions(system_prompt))
        self.synthesizer = dspy.Predict(FinalSynthesisSignature)

    def parse_components(self, proposed_architecture, **kwargs):
        res = self.parser(proposed_architecture=proposed_architecture, **kwargs)
        try:
            # If TypedPredictor is used, res.components_map_json might already be a dict or a string
            if isinstance(res.components_map_json, str):
                json_str = res.components_map_json.strip()
                
                # Check for Markdown JSON blocks
                if "```json" in json_str:
                    json_str = json_str.split("```json")[1].split("```")[0].strip()
                elif "```" in json_str:
                    json_str = json_str.split("```")[1].split("```")[0].strip()
                
                # Handle cases where there's extra data after the JSON (e.g. [[ ## completed ##]])
                if not (json_str.startswith("{") and json_str.endswith("}")):
                    first_brace = json_str.find("{")
                    last_brace = json_str.rfind("}")
                    if first_brace != -1 and last_brace != -1:
                        json_str = json_str[first_brace:last_brace+1]
                
                components_map = json.loads(json_str)
            else:
                components_map = res.components_map_json
            
            return components_map
        except Exception as e:
            log.error(f"Failed to parse components JSON: {e}. Raw output: {res.components_map_json}")
            return {}

    def evaluate_component(self, user_request, finalized_component_names, current_component_name, current_component_details, **kwargs):
        return self.evaluator(
            user_request=user_request,
            finalized_component_names=finalized_component_names,
            current_component_name=current_component_name,
            current_component_details=current_component_details,
            **kwargs
        )
    
    def synthesize_final(self, user_request, finalized_components, **kwargs):
        return self.synthesizer(user_request=user_request, finalized_components=finalized_components, **kwargs)

class AgentPayloadProcessor:
    def prepare_payload(self, task: AgentTask):
        data = task.job_data
        user_request = data.get("user_request", "")
        proposed_text = data.get("text", "")
        communication_type = data.get("communication_type", "p2p")
        model_name = data.get("model_name", "aios:qwen3-1-7b-vllm-block")
        session_id = data.get("session_id", "")
        round_count = int(data.get("round_count", 0))
        return user_request, proposed_text, communication_type, model_name, session_id, round_count

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

class DebateStateManager:
    def load_state(self, session_id):
        finalized = []
        pending = []
        debate_history = {}
        round_count_component = {}
        try:
            if os.path.exists(f"finalized_{session_id}.json"):
                with open(f"finalized_{session_id}.json", "r") as f:
                    finalized = json.load(f)
            if os.path.exists(f"pending_{session_id}.json"):
                with open(f"pending_{session_id}.json", "r") as f:
                    pending = json.load(f)
            if os.path.exists(f"debate_history_{session_id}.json"):
                with open(f"debate_history_{session_id}.json", "r") as f:
                    debate_history = json.load(f)
            if os.path.exists(f"round_count_comp_{session_id}.json"):
                with open(f"round_count_comp_{session_id}.json", "r") as f:
                    round_count_component = json.load(f)
        except Exception as e:
            log.warning(f"Failed to load state: {e}")
        return finalized, pending, debate_history, round_count_component

    def save_state(self, session_id, finalized, pending, debate_history, round_count_component):
        try:
            with open(f"finalized_{session_id}.json", "w") as f:
                json.dump(finalized, f, indent=2)
            with open(f"pending_{session_id}.json", "w") as f:
                json.dump(pending, f, indent=2)
            with open(f"debate_history_{session_id}.json", "w") as f:
                json.dump(debate_history, f, indent=2)
            with open(f"round_count_comp_{session_id}.json", "w") as f:
                json.dump(round_count_component, f, indent=2)
        except Exception as e:
            log.error(f"Failed to save state: {e}")

    def cleanup_state(self, session_id):
        try:
            os.remove(f"finalized_{session_id}.json")
            os.remove(f"pending_{session_id}.json")
            os.remove(f"debate_history_{session_id}.json")
            os.remove(f"round_count_comp_{session_id}.json")
        except: pass

class SeniorArchitectAgent:
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
        self.module = ArchitectEvaluatorModule(self.persona_default_system_message)
        self.payload_processor = AgentPayloadProcessor()
        self.model_context = ModelContextManager(self.aios_dspy_lm)
        self.state_manager = DebateStateManager()
        
        # Next agent (back to Software Agent)
        self.next_agent_subject_id = self.agents_config.get("architecture-debate", {}).get("senior-architect-agent", {}).get("next_agent")
        if not self.next_agent_subject_id:
            self.next_agent_subject_id = "software-agent"

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

    def _load_state(self, session_id):
        finalized = []
        pending = []
        debate_history = {}
        round_count_component = {}
        try:
            if os.path.exists(f"finalized_{session_id}.json"):
                with open(f"finalized_{session_id}.json", "r") as f:
                    finalized = json.load(f)
            if os.path.exists(f"pending_{session_id}.json"):
                with open(f"pending_{session_id}.json", "r") as f:
                    pending = json.load(f)
            if os.path.exists(f"debate_history_{session_id}.json"):
                with open(f"debate_history_{session_id}.json", "r") as f:
                    debate_history = json.load(f)
            if os.path.exists(f"round_count_comp_{session_id}.json"):
                with open(f"round_count_comp_{session_id}.json", "r") as f:
                    round_count_component = json.load(f)
        except Exception as e:
            log.warning(f"Failed to load state: {e}")
        return finalized, pending, debate_history, round_count_component

    def _save_state(self, session_id, finalized, pending, debate_history, round_count_component):
        try:
            with open(f"finalized_{session_id}.json", "w") as f:
                json.dump(finalized, f, indent=2)
            with open(f"pending_{session_id}.json", "w") as f:
                json.dump(pending, f, indent=2)
            with open(f"debate_history_{session_id}.json", "w") as f:
                json.dump(debate_history, f, indent=2)
            with open(f"round_count_comp_{session_id}.json", "w") as f:
                json.dump(round_count_component, f, indent=2)
        except Exception as e:
            log.error(f"Failed to save state: {e}")

    def _execute_parser(self, proposed_text, model_name):
        dummy_session_id = self._generate_dummy_session_id()
        with self.model_context.get_context(model_name, dummy_session_id):
            return self.module.parse_components(proposed_text, session_id=dummy_session_id)

    def _execute_evaluator(self, user_request, model_name, finalized_names, name, details):
        dummy_session_id = self._generate_dummy_session_id()
        with self.model_context.get_context(model_name, dummy_session_id):
            return self.module.evaluate_component(
                user_request=user_request,
                finalized_component_names=finalized_names,
                current_component_name=name,
                current_component_details=details,
                session_id=dummy_session_id
            )

    def _execute_synthesizer(self, user_request, finalized_str, model_name):
        dummy_session_id = self._generate_dummy_session_id()
        with self.model_context.get_context(model_name, dummy_session_id):
            return self.module.synthesize_final(user_request, finalized_str, session_id=dummy_session_id)

    def _prepare_inputs(self, task: AgentTask):
        user_request, proposed_text, communication_type, model_name, session_id, round_count = self.payload_processor.prepare_payload(task)
        
        # Validate input from Software Agent
        if not proposed_text or len(proposed_text) < 50 or proposed_text.startswith("Error:"):
            log.error(f"Received invalid architecture plan from Software Agent: {proposed_text[:100]}...")
            raise ValueError("Invalid or failing architecture proposal received.")

        # Load state
        finalized, pending, debate_history, round_count_component = self.state_manager.load_state(session_id)
        
        # Initial Round: Parse components
        if round_count <= 1 and not pending and not finalized:
            log.info("Initial round: Parsing architecture into components...")
            components_map = self._execute_parser(proposed_text, model_name)
            pending = [{"name": name, "details": desc} for name, desc in components_map.items()]
            if not pending:
                pending = [{"name": "Core Architecture Design", "details": proposed_text}]
            round_count_component = {p["name"]: 0 for p in pending}
            self.state_manager.save_state(session_id, finalized, pending, debate_history, round_count_component)

        # Update current component with Software Agent response
        if round_count > 1 and pending and proposed_text:
            current_comp = pending[0]
            current_comp["details"] = proposed_text
            log.info(f"Updating details for current component: {current_comp['name']}")
            round_count_component[current_comp["name"]] = round_count_component.get(current_comp["name"], 0) + 1

        return user_request, proposed_text, communication_type, model_name, session_id, round_count, finalized, pending, debate_history, round_count_component

    def _evaluate_one(self, user_request, model_name, current_comp, finalized, round_count_component):
        name = current_comp["name"]
        iteration = round_count_component.get(name, 0)
        display_iteration = iteration if iteration > 0 else 1
        
        log.info(f"Evaluating component: {name} (Round: {display_iteration})")
        finalized_names = json.dumps([c["name"] for c in finalized], indent=2)
        
        eval_result = self._execute_evaluator(user_request, model_name, finalized_names, name, current_comp["details"])

        try:
            raw_score = str(eval_result.satisfaction_score).split('/')[0].strip()
            score = int(float(raw_score))
        except Exception:
            log.warning(f"Could not parse score '{eval_result.satisfaction_score}', defaulting to 0.")
            score = 0

        # HIS update
        try:
            msg = (
                f"Evaluating: {name} (Iteration: {iteration})\nScore: {score}/100\n"
                f"Status: {'Approved' if score >= 95 else 'Needs Refinement'}\n"
                f"Reasoning: {eval_result.reasoning}\nFeedback: {eval_result.feedback}"
            )
            self.his_client.submit(input_data={"text": msg})
        except: pass

        return eval_result, score

    def _synthesize_and_finish(self, task, session_id, model_name, user_request, finalized, debate_history):
        log.info("No more pending components. Synthesizing final architecture.")
        finalized_str = json.dumps(finalized, indent=2)
        synthesis = self._execute_synthesizer(user_request, finalized_str, model_name)
        final_report = synthesis.final_architecture_report
        
        try:
            self.his_client.submit(input_data={"text": f"--- FINAL ARCHITECTURE REPORT ---\n{final_report}"})
        except: pass

        self.state_manager.cleanup_state(session_id)

        return AgentResult(
            task_id=task.task_id,
            job_output={"text": final_report, "debate_metadata": debate_history},
            is_error=False
        )

    def _send_to_software_agent(self, task, session_id, model_name, round_count, communication_type, user_request, finalized, pending, debate_history, round_count_component, response_text):
        current_comp = pending[0]
        comp_name = current_comp["name"]
        
        comp_hist_list = debate_history.get(comp_name, [])
        if comp_hist_list:
            last_entry = comp_hist_list[-1]
            round_num = len(comp_hist_list)
            role_msg = "I said below items:" if round_num == 1 else "I said below items for Answering the Architects Doubts:"
            component_history = (
                f"LAST ROUND HISTORY (ROUND {round_num}):\n"
                f"\t{role_msg}\n"
                f"\t\t{last_entry.get('software_agent_proposal', 'N/A')}\n"
                f"\tArchitect Feedback was:\n"
                f"\t\t{last_entry.get('senior_architect_feedback', 'N/A')} (Score: {last_entry.get('score', 0)}/100)"
            )
        else:
            component_history = f"Original Proposal for {comp_name}:\n{current_comp['details']}"

        payload = {
            "text": response_text,
            "user_request": user_request,
            "current_component_name": comp_name,
            "component_history": component_history,
            "finalized_components": json.dumps([c["name"] for c in finalized], indent=2),
            "round_count_component": round_count_component,
            "session_id": session_id,
            "model_name": model_name,
            "round_count": round_count,
            "communication_type": communication_type
        }

        try:
            self.his_client.submit(input_data={"text": f"--- Message to Software Agent ---\n{response_text}"})
        except: pass

        if communication_type == "p2p":
            self.context.p2p_manager.send_sync(task=task, subject_id=self.next_agent_subject_id, job_data=payload, session_id=session_id)
        else:
            self.context.direct.submit(to=self.next_agent_subject_id, session_id=session_id, task=task, job_data=payload)

        return AgentResult(task_id=task.task_id, skip=True)

    def on_data(self, task: AgentTask) -> AgentResult:
        try:
            user_request, proposed_text, communication_type, model_name, session_id, round_count, finalized, pending, debate_history, round_count_component = self._prepare_inputs(task)

            while True:
                if not pending:
                    return self._synthesize_and_finish(task, session_id, model_name, user_request, finalized, debate_history)

                current_comp = pending[0]
                comp_name = current_comp["name"]
                
                eval_result, score = self._evaluate_one(user_request, model_name, current_comp, finalized, round_count_component)
                
                if comp_name not in debate_history:
                    debate_history[comp_name] = []
                
                debate_history[comp_name].append({
                    "iteration": round_count_component.get(comp_name, 0),
                    "software_agent_proposal": current_comp["details"][:500] + "..." if len(current_comp["details"]) > 500 else current_comp["details"],
                    "senior_architect_feedback": eval_result.feedback,
                    "score": score,
                    "reasoning": eval_result.reasoning,
                    "timestamp": str(datetime.now())
                })

                is_approved = score >= 95
                iteration = round_count_component.get(comp_name, 0)
                forced_approval = False
                
                if not is_approved and iteration >= 3:
                    log.warning(f"Component '{comp_name}' reached max iterations ({iteration}). Forcing approval.")
                    is_approved = True
                    forced_approval = True

                if is_approved:
                    log.info(f"Component '{comp_name}' FINALIZED (Score: {score}).")
                    pending.pop(0)
                    if forced_approval:
                         current_comp["details"] = f"{current_comp['details']}\n\n[ARCHITECT LIMIT REACHED] Last Score: {score}. Reasoning: {eval_result.reasoning}"
                    
                    finalized.append(current_comp)
                    self.state_manager.save_state(session_id, finalized, pending, debate_history, round_count_component)
                    continue
                else:
                    log.info(f"Component '{comp_name}' REJECTED (Score: {score}).")
                    response_text = (
                        f"CRITIQUE OF PREVIOUS PROPOSAL (Current Score: {score}/100):\n"
                        f"STRENGTHS & WEAKNESSES: {eval_result.reasoning}\n"
                        f"ACTIONABLE FEEDBACK (FIX THESE): {eval_result.feedback}"
                    )
                    self.state_manager.save_state(session_id, finalized, pending, debate_history, round_count_component)
                    return self._send_to_software_agent(
                        task, session_id, model_name, round_count, communication_type,
                        user_request, finalized, pending, debate_history, round_count_component, response_text
                    )

        except Exception as e:
            log.exception(f"Error in Senior Architect Agent: {e}")
            return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})

if __name__ == "__main__":
    main(SeniorArchitectAgent)
