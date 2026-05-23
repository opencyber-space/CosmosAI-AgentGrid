import logging
import uuid
import json
import time
import dspy
from typing import List, Optional

from agents_sdk.core.agent_executor import AgentResult, AgentTask, Context
from agents_sdk.core.main import main
from agents_sdk.core.his import HisClient
from utils.dspy_aios_llms import AIOS_DSPy_LMs
from utils.json_utils import extract_json

log = logging.getLogger(__name__)

NODE_ID_MAPPING = {
    "agent-workflow-loan-risk-router": "my-router-agent",
    "agent-workflow-financial-profile": "my-financial-profile-agent",
    "agent-workflow-market-risk": "my-market-risk-agent",
    "agent-workflow-collateral-evaluator": "my-collateral-evaluator-agent",
    "workflow-fraud-investigation:1.0.0-production": "my-fraud-investigation-workflow",
    "agent-workflow-loan-decision": "my-loan-decision-agent",
    "agent-workflow-transaction-history": "my-transaction-history-agent",
    "agent-workflow-identity-verification": "my-identity-verification-agent",
    "agent-workflow-fraud-score": "my-fraud-score-agent"
}


# --- 1. The Signatures ---

class MarketRiskSignature(dspy.Signature):
    """
    You are a macroeconomic risk analyst at a commercial bank.

    Given a loan application and the applicant's financial profile, assess the
    macro market conditions and sector-specific risks relevant to the loan.
    Note any market signals that might be inconsistent with the applicant's
    stated financial position (potential fraud indicators).

    Respond ONLY with a valid JSON object in this exact format, no preamble, no markdown:
    {
      "sector":                  "<applicant's employment sector>",
      "market_conditions":       "FAVOURABLE|NEUTRAL|UNFAVOURABLE",
      "interest_rate_risk":      "LOW|MEDIUM|HIGH",
      "sector_employment_trend": "GROWING|STABLE|DECLINING",
      "macro_risk_score":        <1-10>,
      "key_risk_factors":        ["<factor>", ...],
      "market_summary":          "<2-3 sentence summary>",
      "fraud_signals":           ["<any market-level inconsistencies, empty if none>"]
    }
    """
    application_text = dspy.InputField(desc="The loan application text")
    financial_profile_data = dspy.InputField(desc="The financial profile of the applicant")
    market_risk_assessment = dspy.OutputField(desc="Structured JSON with the market risk assessment")

class MarketRiskModule(dspy.Module):
    def __init__(self, system_prompt):
        super().__init__()
        self.assessor = dspy.Predict(MarketRiskSignature)

    def forward(self, application_text, financial_profile_data):
        return self.assessor(
            application_text=application_text,
            financial_profile_data=financial_profile_data
        )

# --- 2. Helper Classes ---

class AgentPayloadProcessor:
    def prepare_payload(self, task: AgentTask):
        data = task.job_data
        communication_type = data.get("communication_type", "delegate")
        model_name = data.get("model_name", "aios:qwen3-1-7b-vllm-block")
        session_id = data.get("session_id", str(uuid.uuid4()))
        return communication_type, model_name, session_id

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

# --- 3. The Agent ---

class MarketRiskAgent:
    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        self.persona_default_system_message = getattr(self.subject.persona, 'default_system_message', "") if hasattr(self.subject, 'persona') else ""
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        self.module = MarketRiskModule(self.persona_default_system_message)
        self.payload_processor = AgentPayloadProcessor()
        self.model_context = ModelContextManager(self.aios_dspy_lm)
        self.task_registry = {}
        
        # Initialize HIS Client
        his_config = getattr(self.subject.persona, 'config', {}).get("parameters", {}).get("HIS_CONFIG", {}) if hasattr(self.subject, 'persona') else {}
        self.his_client = HisClient(
            base_url=his_config["HIS_BASE_URL"],
            poll_interval=his_config.get("HIS_POLL_INTERVAL", 1.0),
            max_wait=his_config.get("HIS_MAX_WAIT", 60)
        )

    def _execute_worker(self, application_text, financial_profile_data, model_name, session_id):
        with self.model_context.get_context(model_name=model_name, session_id=session_id):
            return self.module.forward(
                application_text=application_text,
                financial_profile_data=financial_profile_data
            )

    def _log_to_his(self, target_id, job_data):
        try:
            source_id = self.subject.identity.subject_id
            target_id = {v: k for k, v in NODE_ID_MAPPING.items()}.get(target_id, target_id)
            log.info("Sending HIS log: source_id=%s, destination_id=%s", source_id, target_id)
            msg = {"text": str(job_data), "source_id": source_id, "destination_id": target_id, "team": "Risk Management Team", "timestamp": time.time()}
            self.his_client.submit(input_data=msg)
        except Exception:
            pass

    def get_muxer(self):
        return None

    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        if not task.job_data.get("financial_profile"):
            log.warning("Task %s — missing 'financial_profile', skipping.", task.task_id)
            return None
        return [task]

    def on_data(self, task: AgentTask) -> AgentResult:
        try:
            data = task.job_data
            communication_type, model_name, session_id = self.payload_processor.prepare_payload(task)
            
            self.task_registry[task.task_id] = {
                "model_name": model_name,
                "session_id": session_id
            }
            
            # Log incoming request
            self._log_to_his(
                target_id=self.subject.identity.subject_id, # Self is target of incoming
                job_data={"task_type": "INCOMING_TASK", "payload": data}
            )
            
            application_text = data.get("text", "")
            financial_profile_data = json.dumps(data["financial_profile"], indent=2)

            llm_session_id = str(uuid.uuid4())
            result = self._execute_worker(
                application_text, financial_profile_data, model_name, llm_session_id
            )
            
            extracted_raw = result.market_risk_assessment
            parsed = extract_json(extracted_raw)
            
            log.info("Task %s — market risk complete | macro_risk_score=%s conditions=%s",
                     task.task_id, parsed.get("macro_risk_score"), parsed.get("market_conditions"))

            # Log outgoing result
            self._log_to_his(
                target_id="my-router-agent", # Send to router
                job_data={"task_type": "OUTGOING_RESULT", "payload": parsed}
            )

            return AgentResult(
                task_id=task.task_id,
                job_output=parsed,
                job_output_metadata={
                    "macro_risk_score":   parsed.get("macro_risk_score"),
                    "market_conditions":  parsed.get("market_conditions"),
                },
                is_error=False,
            )

        except Exception as e:
            log.exception("Task %s — unexpected error in on_data: %s", task.task_id, e)
            return AgentResult(
                task_id=task.task_id,
                is_error=True,
                error_data={"stage": "on_data", "message": str(e)},
            )


if __name__ == "__main__":
    main(MarketRiskAgent)
