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

class ControllerSignature(dspy.Signature):
    """
    ### ROLE
    You are the Financial Controller Agent.

    ### TASK
    Evaluate the proposed aggregated budget against the currently available budget.
    Check for overspending risk based on the provided estimates and deliverables. 
    
    ### GUIDELINES FOR EVALUATION
    - First, check if the `total` of all estimates (including buffer) is <= `available_budget`. If it is comfortably within budget, there is NO overarching overspending risk.
    - Small tasks (e.g. 1-2 days of work, minimal deliverables): A reasonable team budget should be 5K - 10K.
    - Large features or full products (e.g. multi-week projects, complex deliverables): A budget can scale properly based on 5K per additional sprint/deliverable, but should not indiscriminately consume the entire available balance.
    - If a single team requests 15,000+ for a very simple deliverable (e.g., just a "Test Plan Document"), flag it as unrealistic.
    
    Provide actionable feedback to the Financial Team Lead so they can make the final approval decision.

    ### OUTPUT
    Output EXACTLY a JSON block.
    """
    aggregated_budget = dspy.InputField(desc="JSON block containing estimates: {estimates: [{team_name: str, amount: float, deliverables: List[str]}], buffer: float, total: float}")
    available_budget = dspy.InputField(desc="The actual funds available in the project ledger")
    output_data = dspy.OutputField(desc="JSON block: {risk_assessment: str, realistic: bool, feedback_to_team_lead: str}")

class ControllerModule(dspy.Module):
    def __init__(self, system_prompt):
        super().__init__()
        self.worker = dspy.ChainOfThought(ControllerSignature)

    def forward(self, aggregated_budget, available_budget):
        return self.worker(aggregated_budget=json.dumps(aggregated_budget), available_budget=str(available_budget))

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

class FinancialControllerAgent:
    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        self.persona_default_system_message = getattr(self.subject.persona, 'default_system_message', "") if hasattr(self.subject, 'persona') else ""
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        
        self.module = ControllerModule(self.persona_default_system_message)
        self.payload_processor = AgentPayloadProcessor()
        self.model_context = ModelContextManager(self.aios_dspy_lm)

        # Initialize HIS Client
        his_config = getattr(self.subject.persona, 'config', {}).get("parameters", {}).get("HIS_CONFIG", {}) if hasattr(self.subject, 'persona') else {}
        self.his_client = HisClient(
            base_url=his_config.get("HIS_BASE_URL", "http://localhost"),
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
            task_id = data.get("task_id", task.task_id)
            user_request = data.get("user_request")
            
            raw_text, communication_type, model_name, session_id = self.payload_processor.prepare_payload(task)
            task_type = data.get("task_type", "validate")

            if task_type == "validate":
                agg_budget = data.get("aggregated_budget")
                avail_budget = data.get("available_budget")
                llm_session_id = data.get("session_id", str(uuid.uuid4()))
                
                with self.model_context.get_context(model_name=model_name, session_id=llm_session_id):
                    result = self.module.forward(aggregated_budget=agg_budget, available_budget=avail_budget)
                
                output_raw = result.output_data
                output_data = extract_json(output_raw)
                
                job_data = {
                    "task_type": "specialist_output",
                    "role": "Financial Controller",
                    "specialist_output": output_data,
                    "task_id": task_id,
                    "user_request": user_request,
                    "session_id": llm_session_id,
                    "model_name": model_name,
                    "communication_type": communication_type
                }

                self._log_to_his("my-company-financial-team-lead-agent", job_data)
                return AgentResult(task_id=task.task_id, job_output=job_data, is_error=False)
            
            return AgentResult(task_id=task.task_id, skip=True)

        except Exception as e:
            log.exception(f"Error in Financial Controller: {e}")
            return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})

if __name__ == "__main__":
    main(FinancialControllerAgent)
