import logging
import uuid
import json
import dspy
from typing import Any, Dict, List, Optional

from agents_sdk.core.agent_executor import AgentResult, AgentTask, Context
from agents_sdk.core.main import main
from agents_sdk.core.his import HisClient
from utils.dspy_aios_llms import AIOS_DSPy_LMs

log = logging.getLogger(__name__)

class StrategistSignature(dspy.Signature):
    """
    ### ROLE
    You are the Financial Strategist Agent.

    ### TASK
    Evaluate the proposed aggregated budget against the currently available budget and project priority.
    Suggest budget cuts or reallocation if total exceeds the priority-based limit or available funds.
    Provide actionable feedback to the Financial Team Lead so they can make the final approval decision.

    ### GUIDELINES FOR EVALUATION
    - IMPORTANT: If the `total` of all estimates is LESS than or EQUAL to the `available_budget`, NO BUDGET SLASHING is needed! You should just approve the estimates as is unless they are wildly unrealistic.
    - If, and ONLY IF, the `total` exceeds the `available_budget`, you MUST suggest budget cuts based on the `priority_level` using the rules below.
    - General slashing logic:
      - Development Teams (Frontend/Backend): NEVER slash their budget deeply. They are critical.
      - Marketing Teams: Typically the first target for heavy budget slashing (e.g. cut by 20%-40%) to save funds.
      - Architecture Teams: If priority is "Premium", do not slash Architecture. If priority is "Fast", Architecture is less critical and can be slashed (e.g. cut by 15%-25%) because the product is just a quick prototype.
    - Provide specific `suggestions` according to these rules.

    ### OUTPUT
    Output EXACTLY a JSON block.
    """
    aggregated_budget = dspy.InputField(desc="JSON block containing estimates: {estimates: [{team_name: str, amount: float, deliverables: List[str]}], buffer: float, total: float}")
    available_budget = dspy.InputField(desc="The actual funds available in the project ledger")
    priority_level = dspy.InputField(desc="The project priority (Cheap, Fast, Premium)")
    output_data = dspy.OutputField(desc="JSON block: {suggestions: List[str], cut_amount: float, feedback_to_team_lead: str}")

class StrategistModule(dspy.Module):
    def __init__(self, system_prompt):
        super().__init__()
        self.worker = dspy.ChainOfThought(StrategistSignature)

    def forward(self, aggregated_budget, available_budget, priority_level):
        return self.worker(aggregated_budget=json.dumps(aggregated_budget), available_budget=str(available_budget), priority_level=priority_level)

class FinancialStrategistAgent:
    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        self.persona_default_system_message = self.subject.persona.default_system_message
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        self.module = StrategistModule(self.persona_default_system_message)
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
            if "aggregated_budget" in task.job_data:
                return [task]
            log.warning("Task %s has no 'text' in job_data, skipping.", task.task_id)
            return None
        return [task]
    def _log_to_his(self, target_id, job_data):
        try:
            msg = {"text": str(job_data), "source_id": self.subject.identity.subject_id, "destination_id": target_id, "team": "Finance Team"}
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
                self.task_registry[task_id] = {"user_request": user_request, "priority": priority}
            else:
                if user_request:
                    self.task_registry[task_id]["user_request"] = user_request
                if "priority" in data:
                    self.task_registry[task_id]["priority"] = priority

            text = data.get("text")
            aggregated_budget = json.loads(text) if isinstance(text, str) and text.startswith("{") else data.get("aggregated_budget")
            available_budget = data.get("available_budget", 70000)
            priority_level = self.task_registry[task_id]["priority"]
            llm_session_id = str(uuid.uuid4())
            model_name = data.get("model_name", "aios:qwen3-1-7b-vllm-block")
            communication_type = data.get("communication_type", "delegate")

            with dspy.settings.context(lm=self.aios_dspy_lm.get_choosen_model(model_name=model_name, session_id=llm_session_id)):
                result = self.module.forward(aggregated_budget=aggregated_budget, available_budget=available_budget, priority_level=priority_level)
            
            output_raw = result.output_data
            output_data = json.loads(output_raw) if isinstance(output_raw, str) else output_raw

            parent_id = "company-financial-team-lead"
            job_data = {
                "task_type": "specialist_output",
                "text": json.dumps({
                    "specialist_output": output_data,
                    "role": "Financial Strategist"
                }),
                "session_id": llm_session_id,
                "model_name": model_name,
                "communication_type": communication_type,
                "task_id": task_id,
                "user_request": self.task_registry[task_id].get("user_request")
            }

            if communication_type == "delegate":
                self._log_to_his(parent_id, job_data)
                self.context.delegator.submit_and_wait(subject_id=parent_id, session_id=llm_session_id, task_id=task.task_id, task_data=job_data)
            else:
                self._log_to_his(parent_id, job_data)
                self.context.p2p_manager.send_sync(task=task, subject_id=parent_id, job_data=job_data, session_id=llm_session_id)

            return AgentResult(task_id=task.task_id, skip=True)

        except Exception as e:
            log.exception(f"Error in Financial Strategist: {e}")
            return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})

if __name__ == "__main__":
    main(FinancialStrategistAgent)
