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
    "agent-workflow-financial-team-lead": "my-company-financial-team-lead-agent",
    "agent-workflow-financial-accountant": "my-company-financial-accountant-agent",
    "agent-workflow-financial-controller": "my-company-financial-controller-agent",
    "agent-workflow-financial-strategist": "my-company-financial-strategist-agent"
}

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

class FinancialAccountantAgent:
    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        self.persona_default_system_message = getattr(self.subject.persona, 'default_system_message', "") if hasattr(self.subject, 'persona') else ""
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        self.module = AccountantModule(self.persona_default_system_message)
        
        self.payload_processor = AgentPayloadProcessor()
        self.model_context = ModelContextManager(self.aios_dspy_lm)
        self.task_registry = {}
        
        # Load initial budget from persona config
        config = getattr(self.subject.persona, 'config', {}) if hasattr(self.subject, 'persona') else {}
        parameters = config.get("parameters", {})
        self.initial_budget = parameters.get("initial_budget", 70000)
        
        # Initialize HIS Client
        his_config = getattr(self.subject.persona, 'config', {}).get("parameters", {}).get("HIS_CONFIG", {}) if hasattr(self.subject, 'persona') else {}
        self.his_client = HisClient(
            base_url=his_config.get("HIS_BASE_URL", "http://localhost"),
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
            source_id = getattr(self.subject.identity, 'subject_id', 'unknown')
            target_id_mapped = {v: k for k, v in NODE_ID_MAPPING.items()}.get(target_id, target_id)
            msg = {"text": str(job_data), "source_id": source_id, "destination_id": target_id_mapped, "team": "Finance Team", "timestamp": time.time()}
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
            
            raw_text, communication_type, model_name, session_id = self.payload_processor.prepare_payload(task)
            
            if task_id not in self.task_registry:
                self.task_registry[task_id] = {
                    "user_request": user_request,
                    "available_budget": float(self.initial_budget)
                }
            elif user_request:
                self.task_registry[task_id]["user_request"] = user_request

            llm_session_id = data.get("session_id", str(uuid.uuid4()))
            output_data = {}

            if task_type == "check_balance":
                log.info(f"Accountant checking balance. Current: {self.task_registry[task_id]['available_budget']}")
                output_data = {
                    "available_budget": self.task_registry[task_id]["available_budget"],
                    "status": "balance_report"
                }
            elif task_type == "deduct_budget":
                amount_to_deduct = float(data.get("amount", 0.0))
                log.info(f"Accountant deducting {amount_to_deduct} from {self.task_registry[task_id]['available_budget']}")
                self.task_registry[task_id]["available_budget"] -= amount_to_deduct
                output_data = {
                    "available_budget": self.task_registry[task_id]["available_budget"],
                    "status": "deducted",
                    "deducted_amount": amount_to_deduct,
                    "decision_data":data.get("decision_data",{})
                }
            else:
                # Default LLM Path for actual accounting work/ledger validation
                text = data.get("text")
                aggregated_budget = json.loads(text) if isinstance(text, str) and text.startswith("{") else data.get("aggregated_budget")
                transactions = data.get("transactions", [])
                
                with self.model_context.get_context(model_name=model_name, session_id=llm_session_id):
                    result = self.module.forward(aggregated_budget=aggregated_budget, transactions=transactions)
                
                output_raw = result.output_data
                output_data = extract_json(output_raw)

            job_data = {
                "task_type": "specialist_output",
                "role": "Financial Accountant",
                "specialist_output": output_data,
                "is_balance_report": task_type == "check_balance",
                "is_deduction_report": task_type == "deduct_budget",
                "session_id": llm_session_id,
                "model_name": model_name,
                "communication_type": communication_type,
                "task_id": task_id,
                "user_request": self.task_registry[task_id].get("user_request")
            }

            self._log_to_his("my-company-financial-team-lead-agent", job_data)
            return AgentResult(task_id=task.task_id, job_output=job_data, is_error=False)

        except Exception as e:
            log.exception(f"Error in Financial Accountant: {e}")
            return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})

if __name__ == "__main__":
    main(FinancialAccountantAgent)
