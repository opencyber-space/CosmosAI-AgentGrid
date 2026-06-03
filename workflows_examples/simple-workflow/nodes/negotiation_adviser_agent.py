import time
import logging
import uuid
import json
import dspy
from typing import List, Optional

from agents_sdk.core.agent_executor import AgentResult, AgentTask, Context
from agents_sdk.core.main import main
from agents_sdk.core.his import HisClient
from utils.dspy_aios_llms import AIOS_DSPy_LMs
from utils.json_utils import extract_json

log = logging.getLogger(__name__)

NODE_ID_MAPPING = {
    "clause-extractor-agent": "my-clause-extractor-agent",
    "risk-identifier-agent": "my-risk-identifier-agent",
    "compliance-checker-agent": "my-compliance-checker-agent",
    "negotiation-adviser-agent": "my-negotiation-advisor-agent",
    "legal-memo-agent": "my-legal-memo-agent"
}

# --- 1. The Signatures ---

class NegotiationAdvisorSignature(dspy.Signature):
    """
    ### ROLE
    You are a commercial contract negotiation specialist representing the client's interests.

    ### TASK
    You will receive identified risks and compliance findings for a contract.
    For each significant issue, produce a concrete redline — a specific suggested replacement
    clause that protects the client.

    For each redline provide:
    - clause_type:  the clause category
    - priority:     HIGH, MEDIUM, or LOW (based on severity and compliance status)
    - original:     the problematic language or clause summary
    - suggested:    the specific replacement language to propose
    - rationale:    1-2 sentences explaining how this protects the client

    Also provide an overall negotiation_stance:
    - REJECT:               if the contract is fundamentally unacceptable
    - NEGOTIATE:            if meaningful redlines can make it acceptable
    - ACCEPT_WITH_CHANGES:  if only minor tweaks are needed

    ### RULES
    Respond ONLY with a valid JSON object, no preamble, no markdown:
    {
      "redlines": [
        {
          "clause_type": "<category>",
          "priority":    "HIGH|MEDIUM|LOW",
          "original":    "<problematic language>",
          "suggested":   "<replacement language>",
          "rationale":   "<rationale>"
        }
      ],
      "negotiation_stance": "REJECT|NEGOTIATE|ACCEPT_WITH_CHANGES"
    }
    """
    contract_risks_and_findings = dspy.InputField(desc="Identified risks and compliance findings")
    negotiation_advice = dspy.OutputField(desc="Structured JSON with redlines and negotiation stance")

class NegotiationAdvisorModule(dspy.Module):
    def __init__(self, system_prompt):
        super().__init__()
        self.advisor = dspy.ChainOfThought(NegotiationAdvisorSignature)

    def forward(self, contract_risks_and_findings):
        return self.advisor(contract_risks_and_findings=contract_risks_and_findings)

# --- 2. Helper Classes ---

class AgentPayloadProcessor:
    def prepare_payload(self, task: AgentTask):
        data = task.job_data
        risks               = data.get("risks", [])
        compliance_findings = data.get("compliance_findings", [])
        
        user_message = (
            "Produce redlines for the following risks and compliance findings:\n\n"
            "RISKS:\n" + json.dumps(risks, indent=2)
            + "\n\nCOMPLIANCE FINDINGS:\n" + json.dumps(compliance_findings, indent=2)
        )
        communication_type = data.get("communication_type", "delegate")
        model_name = data.get("model_name", "aios:qwen3-1-7b-vllm-block")
        session_id = data.get("session_id", str(uuid.uuid4()))
        return user_message, communication_type, model_name, session_id

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

# --- 3. The Negotiation Advisor Agent ---

class NegotiationAdvisorAgent:
    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        self.persona_default_system_message = getattr(self.subject.persona, 'default_system_message', "") if hasattr(self.subject, 'persona') else ""
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        self.module = NegotiationAdvisorModule(self.persona_default_system_message)
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

    def _execute_worker(self, contract_risks_and_findings, model_name, session_id):
        with self.model_context.get_context(model_name=model_name, session_id=session_id):
            return self.module.forward(contract_risks_and_findings=contract_risks_and_findings)

    def _log_to_his(self, target_id, job_data):
        try:
            source_id = getattr(self.subject.identity, 'subject_id', 'unknown')
            target_id_mapped = {v: k for k, v in NODE_ID_MAPPING.items()}.get(target_id, target_id)
            msg = {"text": str(job_data), "source_id": source_id, "destination_id": target_id_mapped, "team": "Legal Team", "timestamp": time.time()}
            self.his_client.submit(input_data=msg)
        except Exception:
            pass

    def get_muxer(self):
        return None

    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        log.info(f"Preprocessing task {task.task_id} {task.job_data}")
        risks    = task.job_data.get("risks")
        findings = task.job_data.get("compliance_findings")
        if not risks or not isinstance(risks, list):
            if "final_project_outcome" not in task.job_data:
                log.warning("Task %s missing or invalid 'risks' in job_data — skipping.", task.task_id)
                return None
        return [task]

    def on_data(self, task: AgentTask) -> AgentResult:
        try:
            data = task.job_data
            if "final_project_outcome" in data:
                log.info(f"Received Final Project Outcome! Task {task.task_id} successfully completed.")
                return AgentResult(task_id=task.task_id, is_error=False, job_output=data)
            
            user_message, communication_type, model_name, session_id = self.payload_processor.prepare_payload(task)

            clauses             = task.job_data.get("clauses", {})
            raw_contract        = task.job_data.get("raw_contract", "")
            overall_score       = task.job_data.get("overall_risk_score", 0)
            high_risk_count     = task.job_data.get("high_risk_count", 0)
            non_compliant_count = task.job_data.get("non_compliant_count", 0)
            risks               = task.job_data.get("risks", [])
            compliance_findings = task.job_data.get("compliance_findings", [])

            self.task_registry[task.task_id] = {
                "user_request": user_message,
                "model_name": model_name,
                "session_id": session_id
            }
            
            # Log incoming request
            self._log_to_his(
                target_id="my-negotiation-advisor-agent", # Self is target of incoming
                job_data={"task_type": "INCOMING_TASK", "payload": data}
            )
            
            log.info(f"Advising negotiation redlines based on identified risks")
            
            llm_session_id = str(uuid.uuid4())
            result = self._execute_worker(user_message, model_name, llm_session_id)
            log.info(f"Negotiation advice result: {result}")
            
            parsed = extract_json(result.negotiation_advice)
            if not parsed and isinstance(result.negotiation_advice, str):
                try:
                    import ast
                    parsed = ast.literal_eval(result.negotiation_advice)
                except:
                    pass
            if not isinstance(parsed, dict):
                parsed = {}
                
            redlines           = parsed.get("redlines", [])
            negotiation_stance = parsed.get("negotiation_stance", "NEGOTIATE")

            job_output = {
                "raw_contract":        raw_contract,
                "clauses":             clauses,
                "risks":               risks,
                "overall_risk_score":  overall_score,
                "high_risk_count":     high_risk_count,
                "compliance_findings": compliance_findings,
                "non_compliant_count": non_compliant_count,
                "redlines":            redlines,
                "negotiation_stance":  negotiation_stance,
            }
            
            # Log outgoing result
            self._log_to_his(
                target_id="my-legal-memo-agent", # Send to next agent
                job_data={"task_type": "OUTGOING_RESULT", "payload": job_output}
            )

            return AgentResult(
                task_id=task.task_id,
                job_output=job_output,
                job_output_metadata={
                    "redlines_count":     len(redlines),
                    "negotiation_stance": negotiation_stance,
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
    main(NegotiationAdvisorAgent)
