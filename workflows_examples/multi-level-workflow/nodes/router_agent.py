import json
import logging
import uuid
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


NODE_FINANCIAL_PROFILE        = "my-financial-profile-agent"
NODE_MARKET_RISK              = "my-market-risk-agent"
NODE_COLLATERAL_EVALUATOR     = "my-collateral-evaluator-agent"
NODE_FRAUD_INVESTIGATION      = "my-fraud-investigation-workflow"
NODE_LOAN_DECISION            = "my-loan-decision-agent"

PARALLEL_PAIR = {NODE_MARKET_RISK, NODE_COLLATERAL_EVALUATOR}

# --- 1. The Signatures ---

class FraudSignalSignature(dspy.Signature):
    """
    You are a financial fraud detection specialist.

    You will receive outputs from a financial profile analysis, market risk and a collateral evaluation
    for a loan application. Your job is to determine whether there are any fraud signals
    that warrant a deep fraud investigation.

    Fraud signals include but are not limited to:
    - Inconsistencies between stated income and financial behaviour
    - Collateral that is grossly insufficient for the loan amount (e.g. LTV > 100% or asking for $1M with only $200K collateral)
    - Unusual transaction patterns or large unexplained cash flows (e.g. sudden large cash deposits without a clear source)
    - Mismatched identity indicators
    - Sudden recent improvements in credit profile
    - High debt-to-income (DTI) ratio combined with poor credit history yielding a high risk of default

    Respond ONLY with a valid JSON object in this exact format, no preamble, no markdown:
    {
      "fraud_signals_result": {
        "fraud_signals_detected": true | false,
        "signals":  ["<signal 1>", "<signal 2>", ...],
        "reasoning": "<1-2 sentence explanation>"
      }
    }
    """
    financial_data = dspy.InputField(desc="Financial profile of the applicant")
    market_data = dspy.InputField(desc="Market risk assessment")
    collateral_data = dspy.InputField(desc="Collateral evaluation")
    fraud_signals_result = dspy.OutputField(desc="Structured JSON with the fraud signals outcome")

class FraudSignalModule(dspy.Module):
    def __init__(self, system_prompt):
        super().__init__()
        self.detector = dspy.Predict(FraudSignalSignature)

    def forward(self, financial_data, market_data, collateral_data):
        return self.detector(
            financial_data=financial_data,
            market_data=market_data,
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

class RouterAgent:

    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        self.persona_default_system_message = getattr(self.subject.persona, 'default_system_message', "") if hasattr(self.subject, 'persona') else ""
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        self.module = FraudSignalModule(self.persona_default_system_message)
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

    def _execute_worker(self, financial_data, market_data, collateral_data, model_name, session_id):
        with self.model_context.get_context(model_name=model_name, session_id=session_id):
            return self.module.forward(
                financial_data=financial_data,
                market_data=market_data,
                collateral_data=collateral_data
            )

    def _log_to_his(self, target_id, job_data):
        try:
            source_id = getattr(self.subject.identity, 'subject_id', 'unknown')
            target_id_mapped = {v: k for k, v in NODE_ID_MAPPING.items()}.get(target_id, target_id)
            msg = {"text": str(job_data), "source_id": source_id, "destination_id": target_id_mapped, "team": "Workflow Router", "timestamp": time.time()}
            self.his_client.submit(input_data=msg)
        except Exception:
            pass

    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        # Router always processes — history can be empty on first call
        if not isinstance(task.job_data, dict):
            log.warning(
                "Task %s — job_data is not a dict (%s), skipping.",
                task.task_id, type(task.job_data).__name__,
            )
            return None
        return [task]

    def get_muxer(self):
        return None

    def on_data(self, task: AgentTask) -> AgentResult:
        try:
            communication_type, model_name, session_id = self.payload_processor.prepare_payload(task)
            
            self.task_registry[task.task_id] = {
                "model_name": model_name,
                "session_id": session_id
            }

            history      = task.job_data.get("history", [])
            outputs      = task.job_data.get("outputs", {})
            initial_input = task.job_data.get("initial_input", {})
            last_executed = task.job_data.get("last_executed")
            last_executed_batch = task.job_data.get("last_executed_batch")

            if last_executed_batch:
                last_node = [node["nodeID"] for node in last_executed_batch]
            elif last_executed:
                last_node = [last_executed["nodeID"]]
            else:
                last_node = []

            log.info(
                "Task %s — router called | last_node=%s | history=%s",
                task.task_id, last_node, history,
            )

            # Log incoming request
            if not last_node:
                self._log_to_his(
                    target_id="my-router-agent", 
                    job_data={"task_type": "ROUTER_INCOMING", "last_node": last_node, "history": history, "initial_input":initial_input}
                )
            else:
                self._log_to_his(
                    target_id="my-router-agent", 
                    job_data={"task_type": "ROUTER_INCOMING", "last_node": last_node, "history": history, "last_executed_batch":last_executed_batch, "last_executed": last_executed}
                )

            next_steps = self._route(
                task_id=task.task_id,
                last_node=last_node,
                history=history,
                outputs=outputs,
                initial_input=initial_input,
                model_name=model_name
            )

            next_nodes = [s["nodeID"] for s in next_steps] if next_steps else []
            
            log.info(
                "Task %s — router decision: %s",
                task.task_id,
                next_nodes if next_nodes else "DONE",
            )

            # Log outgoing request
            for step in next_steps:
                self._log_to_his(
                    target_id=step["nodeID"],
                    job_data={"task_type": "ROUTER_OUTGOING", "payload": step["input"]}
                )

            return AgentResult(
                task_id=task.task_id,
                job_output=next_steps,
                job_output_metadata={"next_nodes": next_nodes},
                is_error=False,
            )

        except Exception as e:
            log.exception("Task %s — unexpected error in router on_data: %s", task.task_id, e)
            return AgentResult(
                task_id=task.task_id,
                is_error=True,
                error_data={"stage": "on_data", "message": str(e)},
            )

    def _route(
        self,
        task_id: str,
        last_node: List[str],
        history: List[str],
        outputs: dict,
        initial_input: dict,
        model_name: str
    ) -> list:
        """
        Pure routing logic — maps workflow state to next steps.
        Returns a list of { nodeID, input } dicts, or [] to signal completion.
        """

        # ── Step 1: First call — no history ────────────────────────────────
        if not last_node:
            log.info("Task %s — Step 1: dispatching financial-profile-agent", task_id)
            return [{
                "nodeID": NODE_FINANCIAL_PROFILE,
                "input":  initial_input,
            }]

        # ── Step 2: After financial-profile — fork to parallel pair ─────────
        if NODE_FINANCIAL_PROFILE in last_node:
            financial_output = outputs.get(NODE_FINANCIAL_PROFILE, {})
            log.info("Task %s — Step 2: forking to market-risk + collateral-evaluator", task_id)
            return [
                {
                    "nodeID": NODE_MARKET_RISK,
                    "input":  {**initial_input, "financial_profile": financial_output},
                },
                {
                    "nodeID": NODE_COLLATERAL_EVALUATOR,
                    "input":  {**initial_input, "financial_profile": financial_output},
                },
            ]

        # ── Step 3 & 4: Waiting / Completing parallel nodes (market-risk & collateral-evaluator) ──────────
        has_market = NODE_MARKET_RISK in last_node
        has_collateral = NODE_COLLATERAL_EVALUATOR in last_node

        if has_market or has_collateral:
            if has_market and has_collateral:
                log.info("Task %s — Step 4: parallel batch execution detected, proceeding to evaluation", task_id)
                return self._route_after_parallel(task_id, outputs, initial_input, model_name)
            else:
                log.info("Task %s — Step 3: waiting for parallel nodes. Both MARKET and COLLATERAL must complete in array.", task_id)
                return []

        # ── Step 5: After fraud investigation ────────────────────────────────
        if NODE_FRAUD_INVESTIGATION in last_node:
            fraud_output = outputs.get(NODE_FRAUD_INVESTIGATION, {})
            log.info("Task %s — Step 5: fraud investigation complete, routing to loan-decision", task_id)
            return [{
                "nodeID": NODE_LOAN_DECISION,
                "input":  {
                    **initial_input,
                    "financial_profile":    outputs.get(NODE_FINANCIAL_PROFILE, {}),
                    "market_risk":          outputs.get(NODE_MARKET_RISK, {}),
                    "collateral":           outputs.get(NODE_COLLATERAL_EVALUATOR, {}),
                    "fraud_investigation":  fraud_output,
                },
            }]

        # ── Step 6: After loan decision — done ───────────────────────────────
        if NODE_LOAN_DECISION in last_node:
            log.info("Task %s — Step 6: loan decision complete, workflow done", task_id)
            return []

        # ── Fallback: unknown state ──────────────────────────────────────────
        log.warning(
            "Task %s — router reached unknown state | last_node=%s history=%s",
            task_id, last_node, history,
        )
        return []

    def _route_after_parallel(
        self,
        task_id: str,
        outputs: dict,
        initial_input: dict,
        model_name: str
    ) -> list:
        """
        Called when both parallel nodes (market-risk + collateral-evaluator) are done.
        Uses OpenAI to detect fraud signals and decides whether to trigger the
        fraud investigation sub-workflow or go straight to loan decision.
        """
        financial_output  = outputs.get(NODE_FINANCIAL_PROFILE, {})
        market_output     = outputs.get(NODE_MARKET_RISK, {})
        collateral_output = outputs.get(NODE_COLLATERAL_EVALUATOR, {})

        try:
            llm_session_id = str(uuid.uuid4())
            result = self._execute_worker(
                financial_data=json.dumps(financial_output, indent=2),
                market_data=json.dumps(market_output, indent=2),
                collateral_data=json.dumps(collateral_output, indent=2),
                model_name=model_name,
                session_id=llm_session_id
            )
            
            extracted_raw = result.fraud_signals_result
            parsed = extract_json(extracted_raw)
            parsed = parsed.get("fraud_signals_result", parsed)
        except Exception as e:
            log.error("Task %s — LLM error during fraud signal detection: %s", task_id, e)
            # Fail safe: escalate to fraud investigation if LLM call fails
            log.warning("Task %s — defaulting to fraud investigation due to LLM error", task_id)
            parsed = {"fraud_signals_detected": True, "signals": ["LLM error — escalating by default"]}

        fraud_detected = parsed.get("fraud_signals_detected", False)
        signals        = parsed.get("signals", [])
        reasoning      = parsed.get("reasoning", "")

        log.info(
            "Task %s — fraud signal detection: detected=%s signals=%s",
            task_id, fraud_detected, signals,
        )

        combined_input = {
            **initial_input,
            "financial_profile": financial_output,
            "market_risk":       market_output,
            "collateral":        collateral_output,
            "fraud_signals":     signals,
            "fraud_reasoning":   reasoning,
        }

        if fraud_detected:
            log.info("Task %s — Step 4: fraud signals detected, routing to fraud-investigation-workflow", task_id)
            return [{
                "nodeID": NODE_FRAUD_INVESTIGATION,
                "input":  combined_input,
            }]
        else:
            log.info("Task %s — Step 4: no fraud signals, routing directly to loan-decision", task_id)
            return [{
                "nodeID": NODE_LOAN_DECISION,
                "input":  combined_input,
            }]


main(RouterAgent)
