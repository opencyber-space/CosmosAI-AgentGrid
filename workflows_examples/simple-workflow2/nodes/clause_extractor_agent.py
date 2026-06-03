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
    "clause-extractor-agent-2": "my-clause-extractor-agent-2",
    "simple-workflow-router-agent": "my-simple-workflow-router-agent",
    "risk-identifier-agent-2": "my-risk-identifier-agent-2",
    "compliance-checker-agent-2": "my-compliance-checker-agent-2",
    "negotiation-adviser-agent-2": "my-negotiation-advisor-agent-2",
    "legal-memo-agent-2": "my-legal-memo-agent-2"
}

NODE_CLAUSE_EXTRACTOR = "my-clause-extractor-agent-2"
NODE_ROUTER = "my-simple-workflow-router-agent"
NODE_RISK_IDENTIFIER = "my-risk-identifier-agent-2"
NODE_COMPLIANCE = "my-compliance-checker-agent-2"
NODE_NEGOTIATION = "my-negotiation-advisor-agent-2"
NODE_LEGAL_MEMO = "my-legal-memo-agent-2"


# --- 1. The Signatures ---

class ClauseExtractorSignature(dspy.Signature):
    """
    ### ROLE
    You are a legal clause extraction specialist.

    ### TASK
    Given a contract text, extract and categorise every clause into the following categories:
    - payment
    - termination
    - liability
    - data_ownership
    - sla
    - renewal
    - jurisdiction

    ### RULES
    Respond ONLY with a valid JSON object in this exact format, no preamble, no markdown. If a clause category is not explicitly found, try to infer it from context, or provide a brief "Not specified" string instead of null:
    {
      "clauses": {
        "payment":        "<verbatim or summarised clause text, or 'Not specified'>",
        "termination":    "<verbatim or summarised clause text, or 'Not specified'>",
        "liability":      "<verbatim or summarised clause text, or 'Not specified'>",
        "data_ownership": "<verbatim or summarised clause text, or 'Not specified'>",
        "sla":            "<verbatim or summarised clause text, or 'Not specified'>",
        "renewal":        "<verbatim or summarised clause text, or 'Not specified'>",
        "jurisdiction":   "<verbatim or summarised clause text, or 'Not specified'>"
      },
      "clause_count": <number of non-empty clauses found>
    }
    """
    contract_text = dspy.InputField(desc="The contract text to analyse")
    extracted_clauses = dspy.OutputField(desc="Structured JSON with extracted clauses and count")

class ClauseExtractorModule(dspy.Module):
    def __init__(self, system_prompt):
        super().__init__()
        self.extractor = dspy.ChainOfThought(ClauseExtractorSignature)

    def forward(self, contract_text):
        return self.extractor(contract_text=contract_text)

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

# --- 3. The Extraction Agent ---

class ClauseExtractorAgent:
    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        self.persona_default_system_message = getattr(self.subject.persona, 'default_system_message', "") if hasattr(self.subject, 'persona') else ""
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        self.module = ClauseExtractorModule(self.persona_default_system_message)
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

    def _execute_worker(self, contract_text, model_name, session_id):
        with self.model_context.get_context(model_name=model_name, session_id=session_id):
            return self.module.forward(contract_text=contract_text)

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
        text = task.job_data.get("text")
        if not text and "final_project_outcome" not in task.job_data:
            log.warning("Task %s has no 'text' or 'final_project_outcome' in job_data, skipping.", task.task_id)
            return None
        if text and len(str(text).strip()) < 20:
            log.warning("Task %s 'text' is too short to be a valid contract (%d chars) — skipping.", task.task_id, len(str(text).strip()))
            return None
        return [task]

    def on_data(self, task: AgentTask) -> AgentResult:
        try:
            data = task.job_data
            if "final_project_outcome" in data:
                log.info(f"Received Final Project Outcome! Task {task.task_id} successfully completed.")
                return AgentResult(task_id=task.task_id, is_error=False, job_output=data, job_output_metadata={})
            
            raw_contract, communication_type, model_name, session_id = self.payload_processor.prepare_payload(task)
            
            self.task_registry[task.task_id] = {
                "user_request": raw_contract,
                "model_name": model_name,
                "session_id": session_id
            }
            
            # Log incoming request
            self._log_to_his(
                target_id=NODE_CLAUSE_EXTRACTOR, # Self is target of incoming
                job_data={"task_type": "INCOMING_TASK", "payload": data}
            )
            
            log.info(f"Extracting clauses from context length {len(raw_contract)}")
            
            llm_session_id = str(uuid.uuid4())
            result = self._execute_worker(raw_contract, model_name, llm_session_id)
            log.info(f"Extraction result: {result}")
            
            extracted_raw = result.extracted_clauses
            parsed = extract_json(extracted_raw)
            
            clauses = parsed.get("clauses", {})
            clause_count = parsed.get("clause_count", sum(1 for v in clauses.values() if v))

            job_output = {
                "raw_contract": raw_contract,
                "clauses": clauses,
                "clause_count": clause_count,
            }
            
            # Log outgoing result
            self._log_to_his(
                target_id=NODE_ROUTER, # Send to next agent
                job_data={"task_type": "OUTGOING_RESULT", "payload": job_output}
            )

            return AgentResult(
                task_id=task.task_id,
                job_output=job_output,
                job_output_metadata={
                    "clause_count": clause_count,
                    "extracted_keys": list(clauses.keys()),
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
    main(ClauseExtractorAgent)
