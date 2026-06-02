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

# --- 1. The Signatures ---

class ComplianceCheckerSignature(dspy.Signature):
    """
    ### ROLE
    You are a regulatory compliance attorney specialising in GDPR, CCPA, and Delaware contract law.

    ### TASK
    You will receive a list of identified contract risks. For each risk, determine whether
    the associated clause is compliant with applicable regulations.

    For each finding provide:
    - clause_type: the clause category
    - regulation:  the specific regulation or legal standard (e.g. "GDPR Article 28", "CCPA Section 1798.100", "Delaware UCC")
    - status:      one of NON_COMPLIANT, AT_RISK, or COMPLIANT
    - detail:      2-3 sentences explaining the compliance determination

    ### RULES
    Respond ONLY with a valid JSON object, no preamble, no markdown:
    {
      "compliance_findings": [
        {
          "clause_type": "<category>",
          "regulation":  "<regulation name and section>",
          "status":      "NON_COMPLIANT|AT_RISK|COMPLIANT",
          "detail":      "<explanation>"
        }
      ],
      "non_compliant_count": <number>
    }
    """
    contract_risks = dspy.InputField(desc="A list of identified contract risks to review")
    compliance_report = dspy.OutputField(desc="Structured JSON array with compliance findings")

class ComplianceCheckerModule(dspy.Module):
    def __init__(self, system_prompt):
        super().__init__()
        self.checker = dspy.ChainOfThought(ComplianceCheckerSignature)

    def forward(self, contract_risks):
        return self.checker(contract_risks=contract_risks)

# --- 2. Helper Classes ---

class AgentPayloadProcessor:
    def prepare_payload(self, task: AgentTask):
        data = task.job_data
        risks = data.get("risks", [])
        communication_type = data.get("communication_type", "delegate")
        model_name = data.get("model_name", "aios:qwen3-1-7b-vllm-block")
        session_id = data.get("session_id", str(uuid.uuid4()))
        return risks, communication_type, model_name, session_id

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

# --- 3. The Compliance Agent ---

class ComplianceCheckerAgent:
    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        self.persona_default_system_message = getattr(self.subject.persona, 'default_system_message', "") if hasattr(self.subject, 'persona') else ""
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        self.module = ComplianceCheckerModule(self.persona_default_system_message)
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

    def _execute_worker(self, contract_risks, model_name, session_id):
        with self.model_context.get_context(model_name=model_name, session_id=session_id):
            return self.module.forward(contract_risks=contract_risks)

    def _log_to_his(self, target_id, job_data):
        try:
            msg = {"text": str(job_data), "source_id": self.subject.identity.subject_id, "destination_id": target_id, "team": "Legal Team"}
            self.his_client.submit(input_data=msg)
        except Exception:
            pass

    def get_muxer(self):
        return None

    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        log.info(f"Preprocessing task {task.task_id} {task.job_data}")
        risks = task.job_data.get("risks")
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
            
            risks_list, communication_type, model_name, session_id = self.payload_processor.prepare_payload(task)
            
            clauses           = task.job_data.get("clauses", {})
            raw_contract      = task.job_data.get("raw_contract", "")
            overall_score     = task.job_data.get("overall_risk_score", 0)
            high_risk_count   = task.job_data.get("high_risk_count", 0)

            user_message = json.dumps(risks_list, indent=2)

            self.task_registry[task.task_id] = {
                "user_request": user_message,
                "model_name": model_name,
                "session_id": session_id
            }
            
            # Log incoming request
            self._log_to_his(
                target_id=self.subject.identity.subject_id, # Self is target of incoming
                job_data={"task_type": "INCOMING_TASK", "payload": data}
            )
            
            log.info(f"Checking compliance for {len(risks_list)} risks")
            
            llm_session_id = str(uuid.uuid4())
            result = self._execute_worker(user_message, model_name, llm_session_id)
            log.info(f"Compliance check result: {result}")
            
            parsed = extract_json(result.compliance_report)
            if not parsed and isinstance(result.compliance_report, str):
                try:
                    import ast
                    parsed = ast.literal_eval(result.compliance_report)
                except:
                    pass
            if not isinstance(parsed, dict):
                parsed = {}
                
            compliance_findings = parsed.get("compliance_findings", [])
            non_compliant_count = parsed.get(
                "non_compliant_count",
                sum(1 for f in compliance_findings if f.get("status") == "NON_COMPLIANT"),
            )

            job_output = {
                "raw_contract":        raw_contract,
                "clauses":             clauses,
                "risks":               risks_list,
                "overall_risk_score":  overall_score,
                "high_risk_count":     high_risk_count,
                "compliance_findings": compliance_findings,
                "non_compliant_count": non_compliant_count,
            }
            
            # Log outgoing result
            self._log_to_his(
                target_id="my-negotiation-advisor-agent", # Send to next agent
                job_data={"task_type": "OUTGOING_RESULT", "payload": job_output}
            )

            return AgentResult(
                task_id=task.task_id,
                job_output=job_output,
                job_output_metadata={
                    "non_compliant_count": non_compliant_count,
                    "findings_count":      len(compliance_findings),
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
    main(ComplianceCheckerAgent)
