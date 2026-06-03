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

class RiskIdentifierSignature(dspy.Signature):
    """
    ### ROLE
    You are a senior legal risk analyst specialising in commercial contracts.

    ### TASK
    You will be given a set of extracted contract clauses. For each clause present,
    identify any risks and assign:
    - clause_type: the category of the clause
    - severity: HIGH, MEDIUM, or LOW
    - score: integer 1-10 (10 = most dangerous)
    - finding: a concise one-line description of the risk
    - reasoning: 2-3 sentences explaining why this is risky

    Also compute an overall_risk_score (1-10) as a weighted average across all risks.

    ### RULES
    Respond ONLY with a valid JSON object, no preamble, no markdown:
    {
      "risks": [
        {
          "clause_type": "<category>",
          "severity":    "HIGH|MEDIUM|LOW",
          "score":       <1-10>,
          "finding":     "<finding>",
          "reasoning":   "<reasoning>"
        }
      ],
      "overall_risk_score": <1-10>,
      "high_risk_count":    <int>
    }
    """
    contract_clauses = dspy.InputField(desc="The extracted contract clauses to evaluate for risks")
    risk_evaluation = dspy.OutputField(desc="Structured JSON with risks array and overall score")

class RiskIdentifierModule(dspy.Module):
    def __init__(self, system_prompt):
        super().__init__()
        self.identifier = dspy.ChainOfThought(RiskIdentifierSignature)

    def forward(self, contract_clauses):
        return self.identifier(contract_clauses=contract_clauses)

# --- 2. Helper Classes ---

class AgentPayloadProcessor:
    def prepare_payload(self, task: AgentTask):
        data = task.job_data
        clauses = data.get("clauses", {})
        
        user_message = (
            "Identify risks in the following contract clauses:\n\n"
            + json.dumps(clauses, indent=2)
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

# --- 3. The Risk Identifier Agent ---

class RiskIdentifierAgent:
    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        self.persona_default_system_message = getattr(self.subject.persona, 'default_system_message', "") if hasattr(self.subject, 'persona') else ""
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        self.module = RiskIdentifierModule(self.persona_default_system_message)
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

    def _execute_worker(self, contract_clauses, model_name, session_id):
        with self.model_context.get_context(model_name=model_name, session_id=session_id):
            return self.module.forward(contract_clauses=contract_clauses)

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
        clauses = task.job_data.get("clauses")
        if not clauses or not isinstance(clauses, dict):
            if "final_project_outcome" not in task.job_data:
                log.warning("Task %s missing or invalid 'clauses' in job_data — skipping.", task.task_id)
                return None
        return [task]

    def on_data(self, task: AgentTask) -> AgentResult:
        try:
            data = task.job_data
            if "final_project_outcome" in data:
                log.info(f"Received Final Project Outcome! Task {task.task_id} successfully completed.")
                return AgentResult(task_id=task.task_id, is_error=False, job_output=data)
            
            user_message, communication_type, model_name, session_id = self.payload_processor.prepare_payload(task)

            clauses      = task.job_data.get("clauses", {})
            raw_contract = task.job_data.get("raw_contract", "")

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
            
            log.info(f"Identifying risks in clauses")
            
            llm_session_id = str(uuid.uuid4())
            result = self._execute_worker(user_message, model_name, llm_session_id)
            log.info(f"Risk identification result: {result}")
            
            parsed = extract_json(result.risk_evaluation)
            if not parsed and isinstance(result.risk_evaluation, str):
                try:
                    import ast
                    parsed = ast.literal_eval(result.risk_evaluation)
                except:
                    pass
            if not isinstance(parsed, dict):
                parsed = {}
                
            risks           = parsed.get("risks", [])
            overall_score   = parsed.get("overall_risk_score", 0)
            high_risk_count = parsed.get(
                "high_risk_count",
                sum(1 for r in risks if r.get("severity") == "HIGH"),
            )

            job_output = {
                "raw_contract":       raw_contract,
                "clauses":            clauses,
                "risks":              risks,
                "overall_risk_score": overall_score,
                "high_risk_count":    high_risk_count,
            }
            
            # Log outgoing result
            self._log_to_his(
                target_id="my-compliance-checker-agent", # Send to next agent
                job_data={"task_type": "OUTGOING_RESULT", "payload": job_output}
            )

            return AgentResult(
                task_id=task.task_id,
                job_output=job_output,
                job_output_metadata={
                    "overall_risk_score": overall_score,
                    "high_risk_count":    high_risk_count,
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
    main(RiskIdentifierAgent)
