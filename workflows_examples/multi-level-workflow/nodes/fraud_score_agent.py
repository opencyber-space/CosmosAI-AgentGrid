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

class FraudScoreSignature(dspy.Signature):
    """
    You are a chief fraud risk officer at a commercial bank.

    You will receive the complete fraud investigation dossier including transaction analysis,
    identity verification results, and all previously detected fraud signals.

    Synthesise all findings into a final fraud risk assessment.

    Respond ONLY with a valid JSON object in this exact format, no preamble, no markdown:
    {
      "fraud_score":          <integer 1-100, 100 = confirmed fraud>,
      "fraud_verdict":        "CLEAR|SUSPICIOUS|HIGH_RISK|CONFIRMED_FRAUD",
      "contributing_factors": ["<factor that contributed to the score>", ...],
      "recommended_action":   "PROCEED|MANUAL_REVIEW|REJECT|REPORT_TO_AUTHORITIES",
      "fraud_summary":        "<3-4 sentence comprehensive summary of findings and recommendation>"
    }
    """
    initial_fraud_signals = dspy.InputField(desc="Initial fraud signals detected")
    fraud_reasoning = dspy.InputField(desc="Reasoning for the initial fraud signals")
    transaction_analysis = dspy.InputField(desc="Transaction analysis results")
    identity_verification = dspy.InputField(desc="Identity verification results")
    collateral = dspy.InputField(desc="Collateral evaluation results")
    fraud_score_assessment = dspy.OutputField(desc="Structured JSON with the final fraud risk assessment")

class FraudScoreModule(dspy.Module):
    def __init__(self, system_prompt):
        super().__init__()
        self.assessor = dspy.Predict(FraudScoreSignature)

    def forward(self, initial_fraud_signals, fraud_reasoning, transaction_analysis, identity_verification, collateral):
        return self.assessor(
            initial_fraud_signals=initial_fraud_signals,
            fraud_reasoning=fraud_reasoning,
            transaction_analysis=transaction_analysis,
            identity_verification=identity_verification,
            collateral=collateral
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

class FraudScoreAgent:
    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        self.persona_default_system_message = getattr(self.subject.persona, 'default_system_message', "") if hasattr(self.subject, 'persona') else ""
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        self.module = FraudScoreModule(self.persona_default_system_message)
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

    def _execute_worker(self, initial_fraud_signals, fraud_reasoning, transaction_analysis, identity_verification, collateral, model_name, session_id):
        with self.model_context.get_context(model_name=model_name, session_id=session_id):
            return self.module.forward(
                initial_fraud_signals=initial_fraud_signals,
                fraud_reasoning=fraud_reasoning,
                transaction_analysis=transaction_analysis,
                identity_verification=identity_verification,
                collateral=collateral
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
        for field in ("transaction_analysis", "identity_verification"):
            if not task.job_data.get(field):
                log.warning("Task %s — missing '%s', skipping.", task.task_id, field)
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
                target_id="my-fraud-score-agent", # Self is target of incoming
                job_data={"task_type": "INCOMING_TASK", "payload": data}
            )
            
            initial_fraud_signals = json.dumps(data.get("fraud_signals", []))
            fraud_reasoning = data.get("fraud_reasoning", "")
            transaction_analysis = json.dumps(data.get("transaction_analysis", {}), indent=2)
            identity_verification = json.dumps(data.get("identity_verification", {}), indent=2)
            collateral = json.dumps(data.get("collateral", {}), indent=2)

            llm_session_id = str(uuid.uuid4())
            result = self._execute_worker(
                initial_fraud_signals, fraud_reasoning, transaction_analysis, identity_verification, collateral, model_name, llm_session_id
            )
            
            extracted_raw = result.fraud_score_assessment
            parsed = extract_json(extracted_raw)
            
            log.info("Task %s — fraud score complete | score=%s verdict=%s action=%s",
                     task.task_id,
                     parsed.get("fraud_score"),
                     parsed.get("fraud_verdict"),
                     parsed.get("recommended_action"))

            # Log outgoing result
            self._log_to_his(
                target_id="my-fraud-score-agent", # The router gets workflow results
                job_data={"task_type": "OUTGOING_RESULT", "payload": parsed}
            )

            return AgentResult(
                task_id=task.task_id,
                job_output=parsed,
                job_output_metadata={
                    "fraud_score":        parsed.get("fraud_score"),
                    "fraud_verdict":      parsed.get("fraud_verdict"),
                    "recommended_action": parsed.get("recommended_action"),
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
    main(FraudScoreAgent)
