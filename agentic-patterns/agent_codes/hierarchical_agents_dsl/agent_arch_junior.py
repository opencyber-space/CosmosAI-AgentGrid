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

class InitialDesignSignature(dspy.Signature):
    """
    ### ROLE
    You are the Junior Architect.

    ### TASK
    Create an initial system architecture proposal based on the problem statement.
    This will be reviewed and brutally critiqued by the Senior Architect.

    ### OUTPUT
    Output EXACTLY a JSON block.
    """
    problem_statement = dspy.InputField(desc="The product idea and core requirements")
    output_data = dspy.OutputField(desc='JSON block: {"proposed_architecture": "str", "components": ["str"]} ')

class DebateResponseSignature(dspy.Signature):
    """
    ### ROLE
    You are the Junior Architect.

    ### TASK
    You are in a debate with the Senior Architect. They have brutally critiqued your previous design.
    You must answer their probing questions and provide a revised architecture that fixes the flaws.

    ### OUTPUT
    Output EXACTLY a JSON block.
    """
    senior_critique = dspy.InputField(desc="The harsh critique and questions from the Senior Architect")
    previous_design = dspy.InputField(desc="Your previous architecture design")
    output_data = dspy.OutputField(desc='JSON block: {"answers_to_critique": "str", "revised_architecture": "str"}')

class JuniorArchModule(dspy.Module):
    def __init__(self, system_prompt):
        super().__init__()
        self.initial_worker = dspy.ChainOfThought(InitialDesignSignature)
        self.debate_worker = dspy.ChainOfThought(DebateResponseSignature)

    def generate_initial(self, problem_statement):
        return self.initial_worker(problem_statement=json.dumps(problem_statement))
        
    def respond_to_critique(self, critique, previous_design):
        return self.debate_worker(senior_critique=json.dumps(critique), previous_design=json.dumps(previous_design))

class JuniorArchAgent:
    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        self.persona_default_system_message = self.subject.persona.default_system_message
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        self.module = JuniorArchModule(self.persona_default_system_message)
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
            # Check for other keys
            if "problem_statement" in task.job_data or "senior_critique" in task.job_data:
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
            senior_design = data.get("senior_design", "No design provided")
            llm_session_id = str(uuid.uuid4())
            model_name = data.get("model_name", "aios:qwen3-1-7b-vllm-block")
            communication_type = data.get("communication_type", "delegate")
            
            task_id = data.get("task_id", task.task_id)
            user_request = data.get("user_request")
            
            priority = data.get("priority", "Fast")
            if task_id not in self.task_registry:
                self.task_registry[task_id] = {"user_request": user_request, "priority": priority}
            else:
                if user_request:
                    self.task_registry[task_id]["user_request"] = user_request
                if "priority" in data:
                    self.task_registry[task_id]["priority"] = priority

            task_type = data.get("task_type", "initial_design")

            with dspy.settings.context(lm=self.aios_dspy_lm.get_choosen_model(model_name=model_name, session_id=llm_session_id)):
                if task_type == "initial_design":
                    problem_statement = data.get("problem_statement", "")
                    result = self.module.generate_initial(problem_statement=problem_statement)
                    current_design = result.output_data
                elif task_type == "revise_design":
                    senior_critique = data.get("senior_critique", "")
                    previous_design = data.get("previous_design", "")
                    result = self.module.respond_to_critique(critique=senior_critique, previous_design=previous_design)
                    current_design = result.output_data
                else:
                    log.warning(f"Junior Architect received unknown task_type: {task_type}")
                    return AgentResult(task_id=task.task_id, skip=True)
            
            output_raw = current_design
            output_data = extract_json(output_raw) if isinstance(output_raw, str) else output_raw

            # Send directly to Senior Architect via P2P
            target_id = "company-arch-senior-agent"
            job_data = {
                "task_type": "evaluate_design",
                "proposed_architecture": output_data,
                "problem_statement": data.get("problem_statement", self.task_registry[task_id].get("user_request")),
                "session_id": llm_session_id,
                "model_name": model_name,
                "communication_type": "p2p",
                "task_id": task_id,
                "user_request": self.task_registry[task_id].get("user_request"),
                "priority": self.task_registry[task_id].get("priority"),
                "deliverables": data.get("deliverables", [])
            }

            self._log_to_his(target_id, job_data)

            self.context.p2p_manager.send_sync(task=task, subject_id=target_id, job_data=job_data, session_id=llm_session_id)

            return AgentResult(task_id=task.task_id, skip=True)

        except Exception as e:
            log.exception(f"Error in Junior Architect: {e}")
            return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})

if __name__ == "__main__":
    main(JuniorArchAgent)
