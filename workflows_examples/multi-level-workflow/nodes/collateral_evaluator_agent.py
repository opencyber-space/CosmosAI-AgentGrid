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

class CollateralExtractionSignature(dspy.Signature):
    """
    Extract the following financial figures from the loan application string text.
    Return ONLY a valid JSON object in this exact format, no preamble or markdown:
    {
      "requested_loan_amount": <float>,
      "estimated_market_value": <float>
    }
    """
    application_text = dspy.InputField(desc="The loan application text")
    extracted_data = dspy.OutputField(desc="Structured JSON with requested_loan_amount and estimated_market_value")

class CollateralEvaluatorSignature(dspy.Signature):
    """
    You are a collateral valuation specialist at a commercial bank.

    Evaluate the collateral offered in the loan application. Check for overvaluation,
    unverifiable assets, or anything inconsistent with the applicant's financial profile.
    Flag any signals that suggest the collateral may be fraudulent or misrepresented.

    CRITICAL INSTRUCTION - PRE-CALCULATED LTV RATIO:
    The exact Loan-to-Value (LTV) ratio has been calculated for you and provided in the input fields.
    
    A good and safe LTV ratio is typically between 70% to 80% (0.7 to 0.8). 
    If the provided LTV ratio is > 1.0, this is EXTREMELY RISKY. 
    You MUST factor this into the `collateral_adequacy` (marking it INADEQUATE) and flag it in `fraud_signals` (e.g., "Grossly insufficient collateral for loan size").

    Respond ONLY with a valid JSON object in this exact format, no preamble, no markdown:
    {
      "collateral_type":        "<e.g. residential property, vehicle, investment portfolio>",
      "stated_value":           <float>,
      "estimated_market_value": <float>,
      "ltv_ratio":              <float>,
      "liquidity":              "HIGH|MEDIUM|LOW",
      "verifiability":          "VERIFIABLE|PARTIALLY_VERIFIABLE|UNVERIFIABLE",
      "collateral_adequacy":    "ADEQUATE|MARGINAL|INADEQUATE",
      "collateral_summary":     "<2-3 sentence summary>",
      "fraud_signals":          ["<overvaluation, unverifiable claims, etc., empty if none>"]
    }
    """
    application_text = dspy.InputField(desc="The loan application text")
    financial_profile = dspy.InputField(desc="The financial profile of the applicant")
    ltv_ratio = dspy.InputField(desc="The exact pre-calculated Loan-to-Value ratio")
    collateral_evaluation = dspy.OutputField(desc="Structured JSON with the extracted collateral evaluation")

class CollateralEvaluatorModule(dspy.Module):
    def __init__(self, system_prompt):
        super().__init__()
        self.extractor = dspy.Predict(CollateralExtractionSignature)
        self.evaluator = dspy.Predict(CollateralEvaluatorSignature)

    def forward(self, application_text, financial_profile):
        ext_result = self.extractor(application_text=application_text)
        
        # Calculate exactly in python
        parsed_ext = extract_json(ext_result.extracted_data)
        ltv_ratio = 1.0 # Safe default
        
        try:
            loan_amt = float(parsed_ext.get("requested_loan_amount", 0))
            market_val = float(parsed_ext.get("estimated_market_value", 0))
            if market_val > 0:
                ltv_ratio = loan_amt / market_val
        except Exception as e:
            log.warning("Failed to calculate explicit LTV from extracted data: %s", e)
            
        # Pass exact calculated ltv to the evaluator
        return self.evaluator(
            application_text=application_text, 
            financial_profile=financial_profile,
            ltv_ratio=str(round(ltv_ratio, 4))
        )

# --- 2. Helper Classes ---

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

# --- 3. The Agent ---

class CollateralEvaluatorAgent:
    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        self.persona_default_system_message = getattr(self.subject.persona, 'default_system_message', "") if hasattr(self.subject, 'persona') else ""
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        self.module = CollateralEvaluatorModule(self.persona_default_system_message)
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

    def _execute_worker(self, application_text, financial_profile, model_name, session_id):
        with self.model_context.get_context(model_name=model_name, session_id=session_id):
            return self.module.forward(application_text=application_text, financial_profile=financial_profile)

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
        if not task.job_data.get("financial_profile"):
            log.warning("Task %s — missing 'financial_profile', skipping.", task.task_id)
            return None
        return [task]

    def on_data(self, task: AgentTask) -> AgentResult:
        try:
            data = task.job_data
            raw_text, communication_type, model_name, session_id = self.payload_processor.prepare_payload(task)
            
            self.task_registry[task.task_id] = {
                "user_request": raw_text,
                "model_name": model_name,
                "session_id": session_id
            }
            
            # Log incoming request
            self._log_to_his(
                target_id="my-collateral-evaluator-agent", # Self is target of incoming
                job_data={"task_type": "INCOMING_TASK", "payload": data}
            )
            
            financial_profile = json.dumps(data["financial_profile"], indent=2)
            llm_session_id = str(uuid.uuid4())
            result = self._execute_worker(raw_text, financial_profile, model_name, llm_session_id)
            
            extracted_raw = result.collateral_evaluation
            parsed = extract_json(extracted_raw)
            
            log.info("Task %s — collateral evaluation complete | adequacy=%s fraud_signals=%d",
                     task.task_id, parsed.get("collateral_adequacy"), len(parsed.get("fraud_signals", [])))

            # Log outgoing result
            self._log_to_his(
                target_id="my-collateral-evaluator-agent", # Send to router
                job_data={"task_type": "OUTGOING_RESULT", "payload": parsed}
            )

            return AgentResult(
                task_id=task.task_id,
                job_output=parsed,
                job_output_metadata={
                    "collateral_adequacy": parsed.get("collateral_adequacy"),
                    "fraud_signals_count": len(parsed.get("fraud_signals", [])),
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
    main(CollateralEvaluatorAgent)
