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

class IdentityVerificationSignature(dspy.Signature):
    """
    You are an identity fraud specialist at a commercial bank's fraud prevention unit.

    Cross-check the applicant's identity information for consistency and signs of fraud.
    Look for mismatched employer details, suspicious address history, document anomalies,
    and any indicators of synthetic identity fraud.

    Respond ONLY with a valid JSON object in this exact format, no preamble, no markdown:
    {
      "identity_verification_result": {
        "identity_consistency":  "CONSISTENT|INCONSISTENT|SUSPICIOUS",
        "employer_verified":     <true|false>,
        "address_history_risk":  "LOW|MEDIUM|HIGH",
        "document_anomalies":    ["<anomaly>", ...],
        "identity_risk_score":   <1-10>,
        "identity_summary":      "<2-3 sentence summary>"
      }
    }
    """
    financial_profile = dspy.InputField(desc="The financial profile of the applicant")
    transaction_analysis = dspy.InputField(desc="Transaction analysis results")
    fraud_signals = dspy.InputField(desc="Detected fraud signals")
    application_text = dspy.InputField(desc="Application text")
    identity_verification_result = dspy.OutputField(desc="Structured JSON with the identity verification results")


class IdentityVerificationModule(dspy.Module):
    def __init__(self, system_prompt):
        super().__init__()
        self.verifier = dspy.Predict(IdentityVerificationSignature)

    def forward(self, financial_profile, transaction_analysis, fraud_signals, application_text):
        return self.verifier(
            financial_profile=financial_profile,
            transaction_analysis=transaction_analysis,
            fraud_signals=fraud_signals,
            application_text=application_text
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

class IdentityVerificationAgent:
    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        self.persona_default_system_message = getattr(self.subject.persona, 'default_system_message', "") if hasattr(self.subject, 'persona') else ""
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        self.module = IdentityVerificationModule(self.persona_default_system_message)
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

    def _execute_worker(self, financial_profile, transaction_analysis, fraud_signals, application_text, model_name, session_id):
        with self.model_context.get_context(model_name=model_name, session_id=session_id):
            return self.module.forward(
                financial_profile=financial_profile,
                transaction_analysis=transaction_analysis,
                fraud_signals=fraud_signals,
                application_text=application_text
            )

    def _log_to_his(self, target_id, job_data):
        try:
            source_id = getattr(self.subject.identity, 'subject_id', 'unknown')
            target_id_mapped = {v: k for k, v in NODE_ID_MAPPING.items()}.get(target_id, target_id)
            msg = {"text": str(job_data), "source_id": source_id, "destination_id": target_id_mapped, "team": "Fraud Prevention Team", "timestamp": time.time()}
            self.his_client.submit(input_data=msg)
        except Exception:
            pass

    def get_muxer(self):
        return None

    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        if not task.job_data.get("transaction_analysis"):
            log.warning("Task %s — missing 'transaction_analysis', skipping.", task.task_id)
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
                target_id="my-identity-verification-agent", # Self is target of incoming
                job_data={"task_type": "INCOMING_TASK", "payload": data}
            )
            
            financial_profile = json.dumps(data.get("financial_profile", {}), indent=2)
            transaction_analysis = json.dumps(data.get("transaction_analysis", {}), indent=2)
            fraud_signals = json.dumps(data.get("fraud_signals", []))
            application_text = data.get("text", "")

            llm_session_id = str(uuid.uuid4())
            result = self._execute_worker(
                financial_profile, transaction_analysis, fraud_signals, application_text, model_name, llm_session_id
            )
            
            extracted_raw = result.identity_verification_result
            parsed = extract_json(extracted_raw)
            identity_verification = parsed.get("identity_verification_result", parsed.get("identity_verification", parsed)) # Be safe against nested
            
            log.info("Task %s — identity verification complete | risk_score=%s consistency=%s",
                     task.task_id,
                     identity_verification.get("identity_risk_score"),
                     identity_verification.get("identity_consistency"))

            # Log outgoing result
            self._log_to_his(
                target_id="my-identity-verification-agent",
                job_data={"task_type": "OUTGOING_RESULT", "payload": identity_verification}
            )

            return AgentResult(
                task_id=task.task_id,
                job_output={**data, "identity_verification": identity_verification},
                job_output_metadata={
                    "identity_risk_score":  identity_verification.get("identity_risk_score"),
                    "identity_consistency": identity_verification.get("identity_consistency"),
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
    main(IdentityVerificationAgent)
