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

class LoanDecisionBaseSignature(dspy.Signature):
    """
    You are a senior loan underwriter at a commercial bank making a final lending decision.

    You will receive a risk dossier on a loan applicant including their
    financial profile, market risk assessment, and collateral evaluation.

    Make a final loan decision:
    - APPROVED:    application meets all criteria
    - CONDITIONAL: approved subject to specific conditions being met
    - REJECTED:    application does not meet minimum criteria

    CRITICAL INSTRUCTION: You MUST respond ONLY with a valid JSON object in the exact format below.
    Do NOT output a single word like "REJECTED" or "APPROVED". You MUST output the full JSON object.
    No preamble, no markdown formatting.

    {
      "loan_decision_result": {
        "decision":          "APPROVED|CONDITIONAL|REJECTED",
        "loan_amount":       <approved float or 0 if rejected>,
        "interest_rate":     <recommended float % or 0 if rejected>,
        "conditions":        ["<condition if CONDITIONAL, empty list otherwise>"],
        "rejection_reasons": ["<reason if REJECTED, empty list otherwise>"],
        "risk_rating":       "A|B|C|D|F",
        "decision_summary":  "<2-3 sentence summary of the decision>",
        "next_steps":        "<what happens next for the applicant>"
      }
    }
    """
    financial_profile_data = dspy.InputField(desc="The financial profile of the applicant")
    market_risk_data = dspy.InputField(desc="Market risk assessment")
    collateral_data = dspy.InputField(desc="Collateral evaluation")
    loan_decision_result = dspy.OutputField(desc="Structured JSON with the final loan decision")

class LoanDecisionWithFraudSignature(dspy.Signature):
    """
    You are a senior loan underwriter at a commercial bank making a final lending decision.

    You will receive a comprehensive risk dossier on a loan applicant including their
    financial profile, market risk assessment, collateral evaluation, and a fraud investigation report.

    Make a final loan decision:
    - APPROVED:    application meets all criteria
    - CONDITIONAL: approved subject to specific conditions being met
    - REJECTED:    application does not meet minimum criteria

    CRITICAL INSTRUCTION: You MUST respond ONLY with a valid JSON object in the exact format below.
    Do NOT output a single word like "REJECTED" or "APPROVED". You MUST output the full JSON object.
    No preamble, no markdown formatting.

    {
      "loan_decision_result": {
        "decision":          "APPROVED|CONDITIONAL|REJECTED",
        "loan_amount":       <approved float or 0 if rejected>,
        "interest_rate":     <recommended float % or 0 if rejected>,
        "conditions":        ["<condition if CONDITIONAL, empty list otherwise>"],
        "rejection_reasons": ["<reason if REJECTED, empty list otherwise>"],
        "risk_rating":       "A|B|C|D|F",
        "decision_summary":  "<2-3 sentence summary of the decision>",
        "next_steps":        "<what happens next for the applicant>"
      }
    }
    """
    financial_profile_data = dspy.InputField(desc="The financial profile of the applicant")
    market_risk_data = dspy.InputField(desc="Market risk assessment")
    collateral_data = dspy.InputField(desc="Collateral evaluation")
    fraud_investigation_data = dspy.InputField(desc="Fraud investigation report")
    fraud_signals_data = dspy.InputField(desc="Initial detected fraud signals")
    loan_decision_result = dspy.OutputField(desc="Structured JSON with the final loan decision")

class LoanDecisionModule(dspy.Module):
    def __init__(self, system_prompt):
        super().__init__()
        self.decider_base = dspy.Predict(LoanDecisionBaseSignature)
        self.decider_fraud = dspy.Predict(LoanDecisionWithFraudSignature)

    def forward(self, financial_profile_data, market_risk_data, collateral_data, fraud_investigation_data=None, fraud_signals_data=None):
        if fraud_investigation_data and fraud_signals_data:
            return self.decider_fraud(
                financial_profile_data=financial_profile_data,
                market_risk_data=market_risk_data,
                collateral_data=collateral_data,
                fraud_investigation_data=fraud_investigation_data,
                fraud_signals_data=fraud_signals_data
            )
        else:
            return self.decider_base(
                financial_profile_data=financial_profile_data,
                market_risk_data=market_risk_data,
                collateral_data=collateral_data
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

class LoanDecisionAgent:
    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        self.persona_default_system_message = getattr(self.subject.persona, 'default_system_message', "") if hasattr(self.subject, 'persona') else ""
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        self.module = LoanDecisionModule(self.persona_default_system_message)
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

    def _execute_worker(self, financial_profile_data, market_risk_data, collateral_data, fraud_investigation_data, fraud_signals_data, model_name, session_id):
        with self.model_context.get_context(model_name=model_name, session_id=session_id):
            return self.module(
                financial_profile_data=financial_profile_data,
                market_risk_data=market_risk_data,
                collateral_data=collateral_data,
                fraud_investigation_data=fraud_investigation_data,
                fraud_signals_data=fraud_signals_data
            )

    def _log_to_his(self, target_id, job_data):
        try:
            source_id = getattr(self.subject.identity, 'subject_id', 'unknown')
            target_id_mapped = {v: k for k, v in NODE_ID_MAPPING.items()}.get(target_id, target_id)
            msg = {"text": str(job_data), "source_id": source_id, "destination_id": target_id_mapped, "team": "Risk Management Team", "timestamp": time.time()}
            self.his_client.submit(input_data=msg)
        except Exception:
            pass

    def get_muxer(self):
        return None

    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        for field in ("financial_profile", "market_risk", "collateral"):
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
                target_id="my-loan-decision-agent", # Self is target of incoming
                job_data={"task_type": "INCOMING_TASK", "payload": data}
            )
            
            fraud_investigation = data.get("fraud_investigation", {})
            fraud_investigation_data = json.dumps(fraud_investigation, indent=2) if fraud_investigation else None
            
            financial_profile_data = json.dumps(data.get("financial_profile", {}), indent=2)
            market_risk_data = json.dumps(data.get("market_risk", {}), indent=2)
            collateral_data = json.dumps(data.get("collateral", {}), indent=2)
            
            fraud_signals = data.get("fraud_signals", [])
            fraud_signals_data = json.dumps(fraud_signals) if fraud_signals else None

            llm_session_id = str(uuid.uuid4())
            result = self._execute_worker(
                financial_profile_data, market_risk_data, collateral_data, fraud_investigation_data, fraud_signals_data, model_name, llm_session_id
            )
            
            extracted_raw = result.loan_decision_result
            try:
                parsed = extract_json(extracted_raw)
                parsed = parsed.get("loan_decision_result", parsed)
            except Exception as e:
                log.warning("Task %s — Failed to parse JSON, falling back. Raw output: %s", task.task_id, extracted_raw)
                decision_status = "REJECTED"
                if "APPROVED" in extracted_raw.upper():
                    decision_status = "APPROVED"
                elif "CONDITIONAL" in extracted_raw.upper():
                    decision_status = "CONDITIONAL"

                parsed = {
                    "decision": decision_status,
                    "loan_amount": 0.0,
                    "interest_rate": 0.0,
                    "conditions": [],
                    "rejection_reasons": ["Automated fallback response due to unstructured LLM output."],
                    "risk_rating": "C",
                    "decision_summary": "Failed to parse final decision JSON, defaulted to safe fallback.",
                    "next_steps": "Manual review required"
                }
            
            log.info("Task %s — loan decision: %s | risk_rating=%s",
                     task.task_id, parsed.get("decision"), parsed.get("risk_rating"))

            # Log outgoing result
            self._log_to_his(
                target_id="my-loan-decision-agent", # Workflow ends, usually returns to router
                job_data={"task_type": "OUTGOING_RESULT", "payload": parsed}
            )

            return AgentResult(
                task_id=task.task_id,
                job_output=parsed,
                job_output_metadata={
                    "decision":     parsed.get("decision"),
                    "risk_rating":  parsed.get("risk_rating"),
                    "loan_amount":  parsed.get("loan_amount"),
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
    main(LoanDecisionAgent)
