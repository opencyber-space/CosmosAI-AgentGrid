import logging
import uuid
import json
import dspy
from typing import Any, Dict, List, Optional

from agents_sdk.core.agent_executor import AgentResult, AgentTask, Context
from agents_sdk.core.main import main
from agents_sdk.core.his import HisClient
from utils.dspy_aios_llms import AIOS_DSPy_LMs
from utils.json_utils import extract_json

log = logging.getLogger(__name__)

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

class SeniorArchAgent:
    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        self.persona_default_system_message = self.subject.persona.default_system_message
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        self.module = SeniorArchModule(self.persona_default_system_message)
        self.task_registry = {}
        # Initialize HIS Client
        his_config = self.subject.persona.config.get("parameters", {}).get("HIS_CONFIG", {})
        self.his_client = HisClient(
            base_url=his_config["HIS_BASE_URL"],
            poll_interval=his_config.get("HIS_POLL_INTERVAL", 1.0),
            max_wait=his_config.get("HIS_MAX_WAIT", 60)
        )



    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        log.info(f"Preprocessing task {task.task_id} {task.job_data}")
        text = task.job_data.get("text")
        if not text:
            # Check for problem_statement
            if "proposed_architecture" in task.job_data:
                return [task]
            log.warning("Task %s has no 'text' in job_data, skipping.", task.task_id)
            return None
        return [task]
    def _log_to_his(self, target_id, job_data):
        try:
            msg = {"text": str(job_data), "source_id": self.subject.identity.subject_id, "destination_id": target_id, "team": "Architecture Team"}
            self.his_client.submit(input_data=msg)
        except Exception:
            pass


    def get_muxer(self):
        return None

    def on_data(self, task: AgentTask) -> AgentResult:
        try:
            data = task.job_data
            
            task_id = data.get("task_id", task.task_id)
            user_request = data.get("user_request")
            
            priority = data.get("priority", "Fast")
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
            proposed_architecture = data.get("proposed_architecture", "No architecture provided")
            problem_statement = data.get("problem_statement", self.task_registry[task_id].get("user_request"))
            deliverables = data.get("deliverables", self.task_registry[task_id]["deliverables"])
            
            # Record Junior's Proposal
            self.task_registry[task_id]["debate_history"].append({
                "iteration": self.task_registry[task_id]["debate_iterations"],
                "junior_proposal": proposed_architecture
            })

            llm_session_id = str(uuid.uuid4())
            model_name = data.get("model_name", "aios:qwen3-1-7b-vllm-block")
            communication_type = data.get("communication_type", "delegate")

            with dspy.settings.context(lm=self.aios_dspy_lm.get_choosen_model(model_name=model_name, session_id=llm_session_id)):
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
                    
                    # Send response back to Junior Architect (P2P)
                    target_id = "company-arch-junior-agent"
                    job_data = {
                        "task_type": "revise_design",
                        "senior_critique": output_data,
                        "previous_design": proposed_architecture,
                        "problem_statement": problem_statement,
                        "session_id": llm_session_id,
                        "model_name": model_name,
                        "communication_type": "p2p",
                        "task_id": task_id,
                        "user_request": self.task_registry[task_id].get("user_request"),
                        "priority": self.task_registry[task_id].get("priority")
                    }
                    self._log_to_his(target_id, job_data)
                    self.context.p2p_manager.send_sync(task=task, subject_id=target_id, job_data=job_data, session_id=llm_session_id)
                else:
                    # Final Blueprint Assembly Mode! (3 iterations are complete)
                    result = self.module.compile_final(
                        problem_statement=problem_statement, 
                        debate_history=self.task_registry[task_id]["debate_history"],
                        deliverables=deliverables
                    )
                    output_raw = result.output_data
                    output_data = extract_json(output_raw) if isinstance(output_raw, str) else output_raw
                    
                    # Routing back to Team Lead
                    target_id = "company-arch-design-team-lead"
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
                    
                    if communication_type == "delegate":
                        self._log_to_his(target_id, job_data)
                        self.context.delegator.submit_and_wait(subject_id=target_id, session_id=llm_session_id, task_id=task.task_id, task_data=job_data)
                    else:
                        self._log_to_his(target_id, job_data)
                        self.context.p2p_manager.send_sync(task=task, subject_id=target_id, job_data=job_data, session_id=llm_session_id)

            return AgentResult(task_id=task.task_id, skip=True)

        except Exception as e:
            log.exception(f"Error in Senior Architect: {e}")
            return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})

if __name__ == "__main__":
    main(SeniorArchAgent)
