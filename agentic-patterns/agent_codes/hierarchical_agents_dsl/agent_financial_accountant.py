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

class AccountantSignature(dspy.Signature):
    """
    ### ROLE
    You are the Financial Accountant Agent.

    ### TASK
    Maintain a running ledger of allocated funds.
    Track the remaining budget based on team approvals and spending reports.

    ### OUTPUT
    Output EXACTLY a JSON block.
    """
    aggregated_budget = dspy.InputField(desc="The current aggregated budget")
    transactions = dspy.InputField(desc="List of approved spending transactions")
    output_data = dspy.OutputField(desc="JSON block: {ledger_summary: str, remaining_balance: float}")

class AccountantModule(dspy.Module):
    def __init__(self, system_prompt):
        super().__init__()
        self.worker = dspy.ChainOfThought(AccountantSignature)

    def forward(self, aggregated_budget, transactions):
        return self.worker(aggregated_budget=json.dumps(aggregated_budget), transactions=json.dumps(transactions))

class FinancialAccountantAgent:
    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        self.persona_default_system_message = self.subject.persona.default_system_message
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        self.module = AccountantModule(self.persona_default_system_message)
        self.task_registry = {}
        
        # Load initial budget from persona config
        config = self.subject.persona.config or {}
        parameters = config.get("parameters", {})
        self.initial_budget = parameters.get("initial_budget", 70000)
        # Initialize HIS Client
        his_config = self.subject.persona.config.get("parameters", {}).get("HIS_CONFIG", {})
        self.his_client = HisClient(
            base_url=his_config["HIS_BASE_URL"],
            poll_interval=his_config.get("HIS_POLL_INTERVAL", 1.0),
            max_wait=his_config.get("HIS_MAX_WAIT", 60)
        )



    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        log.info(f"Preprocessing task {task.task_id} {task.job_data}")
        task_type = task.job_data.get("task_type")
        if task_type in ["check_balance", "deduct_budget"]:
            return [task]
            
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
            task_type = data.get("task_type", "account")
            
            task_id = data.get("task_id", task.task_id)
            user_request = data.get("user_request")
            
            if task_id not in self.task_registry:
                self.task_registry[task_id] = {
                    "user_request": user_request,
                    "available_budget": float(self.initial_budget)
                }
            elif user_request:
                self.task_registry[task_id]["user_request"] = user_request

            llm_session_id = str(uuid.uuid4())
            model_name = data.get("model_name", "aios:qwen3-1-7b-vllm-block")
            communication_type = data.get("communication_type", "delegate")
            parent_id = "company-financial-team-lead"
            
            output_data = {}

            if task_type == "check_balance":
                output_data = {
                    "available_budget": self.task_registry[task_id]["available_budget"],
                    "status": "balance_report"
                }
            elif task_type == "deduct_budget":
                amount_to_deduct = float(data.get("amount", 0.0))
                self.task_registry[task_id]["available_budget"] -= amount_to_deduct
                output_data = {
                    "available_budget": self.task_registry[task_id]["available_budget"],
                    "status": "deducted",
                    "deducted_amount": amount_to_deduct
                }
            else:
                # Default LLM Path for actual accounting work/validation if needed
                text = data.get("text")
                aggregated_budget = json.loads(text) if isinstance(text, str) and text.startswith("{") else data.get("aggregated_budget")
                transactions = data.get("transactions", [])
                
                with dspy.settings.context(lm=self.aios_dspy_lm.get_choosen_model(model_name=model_name, session_id=llm_session_id)):
                    result = self.module.forward(aggregated_budget=aggregated_budget, transactions=transactions)
                
                output_raw = result.output_data
                output_data = json.loads(output_raw) if isinstance(output_raw, str) else output_raw

            job_data = {
                "task_type": "specialist_output",
                "text": json.dumps({
                    "specialist_output": output_data,
                    "role": "Financial Accountant",
                    "is_balance_report": task_type == "check_balance",
                    "is_deduction_report": task_type == "deduct_budget"
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
            log.exception(f"Error in Financial Accountant: {e}")
            return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})

if __name__ == "__main__":
    main(FinancialAccountantAgent)
