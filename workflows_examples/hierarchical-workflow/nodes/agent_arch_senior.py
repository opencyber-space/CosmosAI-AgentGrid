import logging
import uuid
import json
import time
import dspy
from typing import Any, Dict, List, Optional

from agents_sdk.core.agent_executor import AgentResult, AgentTask, Context
from agents_sdk.core.main import main
from agents_sdk.core.his import HisClient
from utils.dspy_aios_llms import AIOS_DSPy_LMs
from utils.json_utils import extract_json

log = logging.getLogger(__name__)

NODE_ID_MAPPING = {
    "agent-workflow-arch-design-team-lead": "my-company-arch-design-team-lead-agent",
    "agent-workflow-arch-junior": "my-company-arch-junior-agent",
    "agent-workflow-arch-senior": "my-company-arch-senior-agent"
}

WORKFLOW_AGENT_SENIOR_ARCHITECT_ID="agent-workflow-arch-senior"
WORKFLOW_AGENT_JUNIOR_ARCHITECT_ID="agent-workflow-arch-junior"
WORKFLOW_AGENT_TEAM_LEAD_ARCHITECT_ID="agent-workflow-arch-design-team-lead"

class SeniorDebateSignature(dspy.Signature):
    """
    ### ROLE
    You are the Senior Architect.

    ### TASK
    You are reviewing an architecture proposal from the Junior Architect.
    You must ruthlessly critique it. Ask incredibly complex, technical probing questions.
    Assume the design has efficiency bottlenecks and point them out. 
    Verify whether the proposed architecture actually fulfills the provided problem statement.
    Do NOT provide the answers; force the Junior to justify or fix their design.

    ### OUTPUT
    Output EXACTLY a JSON block.
    """
    problem_statement = dspy.InputField(desc="The product idea and core requirements")
    junior_architecture = dspy.InputField(desc="The system design proposed by the Junior Architect")
    output_data = dspy.OutputField(desc='JSON block: {"critique_and_questions": "str"}')

class FinalAssemblerSignature(dspy.Signature):
    """
    ### ROLE
    You are the Senior Architect.

    ### TASK
    After 3 rounds of debate, compile the final system blueprint.
    Merge the best parts of the Junior's revised architectures and your own expertise.

    ### OUTPUT
    Output EXACTLY a JSON block.
    """
    problem_statement = dspy.InputField(desc="The product idea and core requirements")
    debate_history = dspy.InputField(desc="The full history of proposals and critiques over 3 rounds")
    deliverables = dspy.InputField(desc="The specific array of deliverables expected from this architecture design step")
    output_data = dspy.OutputField(desc='JSON block: {"final_blueprint": "str"}')

class SeniorArchModule(dspy.Module):
    def __init__(self, system_prompt):
        super().__init__()
        self.debate_worker = dspy.ChainOfThought(SeniorDebateSignature)
        self.assembly_worker = dspy.ChainOfThought(FinalAssemblerSignature)

    def critique_architecture(self, architecture, problem_statement):
        return self.debate_worker(junior_architecture=json.dumps(architecture), problem_statement=json.dumps(problem_statement))
        
    def compile_final(self, problem_statement, debate_history, deliverables):
        return self.assembly_worker(problem_statement=json.dumps(problem_statement), debate_history=json.dumps(debate_history), deliverables=json.dumps(deliverables))

class AgentPayloadProcessor:
    def prepare_payload(self, task: AgentTask):
        data = task.job_data
        raw_text = data.get("text") or data.get("user_request") or ""
        communication_type = data.get("communication_type", "delegate")
        model_name = data.get("model_name", "aios:qwen3-1-7b-vllm-block")
        session_id = data.get("session_id", str(uuid.uuid4()))
        return raw_text, communication_type, model_name, session_id

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

class SeniorArchAgent:
    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        self.persona_default_system_message = getattr(self.subject.persona, 'default_system_message', "") if hasattr(self.subject, 'persona') else ""
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        self.module = SeniorArchModule(self.persona_default_system_message)
        
        self.payload_processor = AgentPayloadProcessor()
        self.model_context = ModelContextManager(self.aios_dspy_lm)
        self.task_registry = {}
        
        # Initialize HIS Client
        his_config = getattr(self.subject.persona, 'config', {}).get("parameters", {}).get("HIS_CONFIG", {}) if hasattr(self.subject, 'persona') else {}
        self.his_client = HisClient(
            base_url=his_config.get("HIS_BASE_URL", "http://localhost"),
            poll_interval=his_config.get("HIS_POLL_INTERVAL", 1.0),
            max_wait=his_config.get("HIS_MAX_WAIT", 60)
        )

    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        log.info(f"Preprocessing task {task.task_id} {task.job_data}")
        data = task.job_data
        if not isinstance(data, dict):
            data = {}
        if "initial_input" in data and isinstance(data["initial_input"], dict):
            data = data["initial_input"]
        task_type = data.get("task_type")
        if task_type not in ["execute_task", "evaluate_design"]:
            log.warning("Task %s has task_type %s, which is not architecture action, skipping.", task.task_id, task_type)
            return None
        return [task]

    def _log_to_his(self, target_id, job_data):
        try:
            source_id = getattr(self.subject.identity, 'subject_id', 'unknown')
            target_id_mapped = {v: k for k, v in NODE_ID_MAPPING.items()}.get(target_id, target_id)
            msg = {"text": str(job_data), "source_id": source_id, "destination_id": target_id_mapped, "team": "Architecture Team", "timestamp": time.time()}
            self.his_client.submit(input_data=msg)
        except Exception:
            pass

    def get_muxer(self):
        return None

    def on_data(self, task: AgentTask) -> AgentResult:
        try:
            data = task.job_data
            if not isinstance(data, dict):
                data = {}
            if "initial_input" in data and isinstance(data["initial_input"], dict):
                log.info("Unpacking dynamic router payload in Senior Architect")
                data = data.get("initial_input", {})
                
            task_id = data.get("task_id", task.task_id)
            user_request = data.get("user_request")
            priority = data.get("priority", "Fast")
            
            raw_text, communication_type, model_name, session_id = self.payload_processor.prepare_payload(task)
            # Re-read parameters from unpacked data
            communication_type = data.get("communication_type", communication_type)
            model_name = data.get("model_name", model_name)
            session_id = data.get("session_id", session_id)
            llm_session_id = session_id

            if task_id not in self.task_registry:
                deliverables = data.get("deliverables", [])
                self.task_registry[task_id] = {
                    "user_request": user_request, 
                    "priority": priority,
                    "debate_iterations": 0,
                    "debate_history": [],
                    "deliverables": deliverables
                }
            else:
                if user_request:
                    self.task_registry[task_id]["user_request"] = user_request
                if "priority" in data:
                    self.task_registry[task_id]["priority"] = priority

            task_type = data.get("task_type", "evaluate_design")
            problem_statement = data.get("problem_statement")
            if not problem_statement:
                text = data.get("text")
                extracted = extract_json(text) if text else None
                problem_statement = extracted if isinstance(extracted, dict) else (text or data.get("problem_statement") or raw_text)

            deliverables = data.get("deliverables", self.task_registry[task_id]["deliverables"])

            if task_type == "execute_task":
                # Team Lead initiated. Senior delegates "initial_design" to Junior.
                job_data = {
                    "task_type": "initial_design",
                    "problem_statement": problem_statement,
                    "session_id": llm_session_id,
                    "model_name": model_name,
                    "communication_type": communication_type,
                    "task_id": task_id,
                    "user_request": self.task_registry[task_id].get("user_request"),
                    "priority": self.task_registry[task_id].get("priority"),
                    "deliverables": deliverables
                }
                
                target_id = "my-company-arch-junior-agent"
                self._log_to_his(target_id, job_data)
                
                if communication_type == "delegate":
                    self.context.delegator.submit_and_wait(subject_id=WORKFLOW_AGENT_JUNIOR_ARCHITECT_ID, session_id=llm_session_id, task_id=task.task_id, task_data=job_data)
                else:
                    self.context.p2p_manager.send_sync(task=task, subject_id=WORKFLOW_AGENT_JUNIOR_ARCHITECT_ID, job_data=job_data, session_id=llm_session_id)
                
                return AgentResult(task_id=task.task_id, skip=True)

            elif task_type == "evaluate_design":
                # Evaluates Junior's proposal
                proposed_architecture = data.get("proposed_architecture", "No architecture provided")
                
                # Record Junior's Proposal
                self.task_registry[task_id]["debate_history"].append({
                    "iteration": self.task_registry[task_id]["debate_iterations"],
                    "junior_proposal": proposed_architecture
                })

                with self.model_context.get_context(model_name=model_name, session_id=llm_session_id):
                    if self.task_registry[task_id]["debate_iterations"] < 2:
                        # Critique Mode (Rounds 0, 1, 2)
                        self.task_registry[task_id]["debate_iterations"] += 1
                        
                        result = self.module.critique_architecture(
                            architecture=proposed_architecture, 
                            problem_statement=problem_statement
                        )
                        output_raw = result.output_data
                        output_data = extract_json(output_raw) if isinstance(output_raw, str) else output_raw
                        
                        # Record Senior's Critique
                        self.task_registry[task_id]["debate_history"][-1]["senior_critique"] = output_data
                        
                        target_id = "my-company-arch-junior-agent"
                        job_data = {
                            "task_type": "revise_design",
                            "senior_critique": output_data,
                            "previous_design": proposed_architecture,
                            "problem_statement": problem_statement,
                            "session_id": llm_session_id,
                            "model_name": model_name,
                            "communication_type": communication_type,
                            "task_id": task_id,
                            "user_request": self.task_registry[task_id].get("user_request"),
                            "priority": self.task_registry[task_id].get("priority"),
                            "deliverables": deliverables
                        }
                        self._log_to_his(target_id, job_data)
                        
                        if communication_type == "delegate":
                            self.context.delegator.submit_and_wait(subject_id=WORKFLOW_AGENT_JUNIOR_ARCHITECT_ID, session_id=llm_session_id, task_id=task.task_id, task_data=job_data)
                        else:
                            self.context.p2p_manager.send_sync(task=task, subject_id=WORKFLOW_AGENT_JUNIOR_ARCHITECT_ID, job_data=job_data, session_id=llm_session_id)
                            
                        return AgentResult(task_id=task.task_id, skip=True)
                    else:
                        # Final Blueprint Assembly Mode! (3 iterations are complete)
                        result = self.module.compile_final(
                            problem_statement=problem_statement, 
                            debate_history=self.task_registry[task_id]["debate_history"],
                            deliverables=deliverables
                        )
                        output_raw = result.output_data
                        output_data = extract_json(output_raw) if isinstance(output_raw, str) else output_raw
                        
                        target_id = "my-company-arch-design-team-lead-agent"
                        job_data = {
                            "task_type": "final_blueprint",
                            "final_blueprint": output_data.get("final_blueprint", output_data),
                            "session_id": llm_session_id,
                            "model_name": model_name,
                            "communication_type": communication_type,
                            "task_id": task_id,
                            "user_request": self.task_registry[task_id].get("user_request"),
                            "priority": self.task_registry[task_id].get("priority")
                        }
                        
                        self._log_to_his(target_id, job_data)
                        # if communication_type == "delegate":
                        #     self.context.delegator.submit_and_wait(subject_id=WORKFLOW_AGENT_TEAM_LEAD_ARCHITECT_ID, session_id=llm_session_id, task_id=task.task_id, task_data=job_data)
                        # else:
                        #     self.context.p2p_manager.send_sync(task=task, subject_id=WORKFLOW_AGENT_TEAM_LEAD_ARCHITECT_ID, job_data=job_data, session_id=llm_session_id)
                            
                        #return AgentResult(task_id=task.task_id, skip=True)
                        return AgentResult(
                            task_id=task.task_id,
                            job_output=job_data,
                            job_output_metadata={},
                            is_error=False,
                        )

            # return AgentResult(task_id=task.task_id, skip=True)

        except Exception as e:
            log.exception(f"Error in Senior Architect: {e}")
            return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})

if __name__ == "__main__":
    main(SeniorArchAgent)
