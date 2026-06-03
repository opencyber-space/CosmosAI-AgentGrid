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

# --- 1. The Signatures ---

class LegalMemoSignature(dspy.Signature):
    """
    ### ROLE
    You are a senior legal counsel drafting an internal memo for a client's legal team.

    ### TASK
    You will receive a full contract analysis including extracted clauses, identified risks,
    compliance findings, and proposed redlines.

    Produce a concise, professional legal memo with the following sections:
    - executive_summary:    2-3 sentences summarising the overall situation and recommendation
    - key_risks:            prose paragraph covering the most critical risks
    - compliance_issues:    prose paragraph covering any regulatory compliance concerns
    - recommended_redlines: prose paragraph summarising the most important redlines to push for
    - recommendation:       one of REJECT, NEGOTIATE, or ACCEPT_WITH_CHANGES
    - next_steps:           3-5 concrete, actionable next steps as a newline-separated list

    ### RULES
    Respond ONLY with a valid JSON object, no preamble, no markdown:
    {
      "memo": {
        "executive_summary":    "<text>",
        "key_risks":            "<text>",
        "compliance_issues":    "<text>",
        "recommended_redlines": "<text>",
        "recommendation":       "REJECT|NEGOTIATE|ACCEPT_WITH_CHANGES",
        "next_steps":           "<text>"
      }
    }
    """
    contract_analysis = dspy.InputField(desc="A full contract analysis to draft the memo from")
    drafted_memo = dspy.OutputField(desc="Structured JSON object representing the legal memo")

class LegalMemoModule(dspy.Module):
    def __init__(self, system_prompt):
        super().__init__()
        self.memo_drafter = dspy.ChainOfThought(LegalMemoSignature)

    def forward(self, contract_analysis):
        return self.memo_drafter(contract_analysis=contract_analysis)

# --- 2. Helper Classes ---

class AgentPayloadProcessor:
    def prepare_payload(self, task: AgentTask):
        data = task.job_data
        clauses             = data.get("clauses", {})
        risks               = data.get("risks", [])
        compliance_findings = data.get("compliance_findings", [])
        redlines            = data.get("redlines", [])
        overall_score       = data.get("overall_risk_score", 0)
        high_risk_count     = data.get("high_risk_count", 0)
        non_compliant_count = data.get("non_compliant_count", 0)
        negotiation_stance  = data.get("negotiation_stance", "NEGOTIATE")

        user_message = (
            "Draft a legal memo based on the following contract analysis.\n\n"
            "CLAUSES:\n"             + json.dumps(clauses, indent=2)
            + "\n\nRISKS:\n"         + json.dumps(risks, indent=2)
            + "\n\nCOMPLIANCE FINDINGS:\n" + json.dumps(compliance_findings, indent=2)
            + "\n\nPROPOSED REDLINES:\n"   + json.dumps(redlines, indent=2)
            + f"\n\nNEGOTIATION STANCE: {negotiation_stance}"
            + f"\nOVERALL RISK SCORE: {overall_score}/10"
            + f"\nHIGH RISK CLAUSES: {high_risk_count}"
            + f"\nNON-COMPLIANT CLAUSES: {non_compliant_count}"
        )
        
        communication_type = data.get("communication_type", "delegate")
        model_name = data.get("model_name", "aios:qwen3-1-7b-vllm-block")
        session_id = data.get("session_id", str(uuid.uuid4()))
        return user_message, communication_type, model_name, session_id, overall_score, negotiation_stance

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

# --- 3. The Legal Memo Agent ---

class LegalMemoAgent:
    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        self.persona_default_system_message = getattr(self.subject.persona, 'default_system_message', "") if hasattr(self.subject, 'persona') else ""
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        self.module = LegalMemoModule(self.persona_default_system_message)
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

    def _execute_worker(self, contract_analysis, model_name, session_id):
        with self.model_context.get_context(model_name=model_name, session_id=session_id):
            return self.module.forward(contract_analysis=contract_analysis)

    def _log_to_his(self, target_id, job_data):
        try:
            msg = {"text": str(job_data), "source_id": self.subject.identity.subject_id, "destination_id": target_id, "team": "Legal Team", "timestamp": time.time()}
            self.his_client.submit(input_data=msg)
        except Exception:
            pass

    def get_muxer(self):
        return None

    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        log.info(f"Preprocessing task {task.task_id} {task.job_data}")
        for field in ("risks", "compliance_findings", "redlines"):
            if not task.job_data.get(field):
                if "final_project_outcome" not in task.job_data:
                    log.warning(
                        "Task %s missing '%s' in job_data — skipping.",
                        task.task_id, field,
                    )
                    return None
        return [task]

    def on_data(self, task: AgentTask) -> AgentResult:
        try:
            data = task.job_data
            if "final_project_outcome" in data:
                log.info(f"Received Final Project Outcome! Task {task.task_id} successfully completed.")
                return AgentResult(task_id=task.task_id, is_error=False, job_output=data)
            
            user_message, communication_type, model_name, session_id, overall_score, negotiation_stance = self.payload_processor.prepare_payload(task)

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
            
            log.info(f"Drafting legal memo based on complete analysis")
            
            llm_session_id = str(uuid.uuid4())
            result = self._execute_worker(user_message, model_name, llm_session_id)
            log.info(f"Legal Memo drafting result: {result}")
            
            parsed = extract_json(result.drafted_memo)
            log.info(f"[DEBUG] extract_json returned type: {type(parsed)}")
            
            if not parsed and isinstance(result.drafted_memo, str):
                try:
                    import ast
                    parsed = ast.literal_eval(result.drafted_memo)
                    log.info(f"[DEBUG] ast literal_eval succeeded, type: {type(parsed)}")
                except:
                    pass
            
            if not isinstance(parsed, dict):
                log.info(f"[DEBUG] parsed is NOT a dict. It is: {type(parsed)}. Setting to {{}}")
                parsed = {}
                
            memo = parsed.get("memo") if "memo" in parsed else parsed
            log.info(f"[DEBUG] memo constructed: keys=({hasattr(memo, 'keys') and memo.keys()})")

            job_output = {
                "final_memo":          memo,
                "overall_risk_score":  overall_score,
                "negotiation_stance":  negotiation_stance,
            }
            
            # Log outgoing result
            self._log_to_his(
                target_id="End of Workflow", # Last agent, so send to End of Workflow
                job_data={"task_type": "OUTGOING_RESULT", "payload": job_output}
            )

            return AgentResult(
                task_id=task.task_id,
                job_output=job_output,
                job_output_metadata={
                    "recommendation": memo.get("recommendation"),
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
    main(LegalMemoAgent)
