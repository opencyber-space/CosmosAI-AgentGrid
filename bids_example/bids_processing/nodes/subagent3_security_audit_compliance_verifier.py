import logging
import time
from agents_sdk.core.his import HisClient
import uuid
import json
import dspy
from dspy.utils.exceptions import AdapterParseError
from typing import Any, Dict, List, Optional

from agents_sdk.core.agent_executor import AgentTask, AgentResult, Context
from agents_sdk.core.main import main
from utils.dspy_aios_llms import AIOS_DSPy_LMs
from utils.json_utils import extract_json

log = logging.getLogger(__name__)

MANAGER_ID = "manager1-security-audit"


# --- Signatures ---

class SubagentAssessSignature(dspy.Signature):
    """
    ### ROLE
    You are Sub-agent 3: Compliance Verifier.

    ### TASK
    Assess the sub-task instruction for compliance auditing (PCI-DSS, SOC2, GDPR). Determine if you can perform this sub-task and estimate token usage, compute requirements, testing environment needs, and any constraints.

    ### OUTPUT
    Output EXACTLY a JSON block: {"can_do": bool, "approx_tokens": int, "compute_required": "low|moderate|high", "testing_env": "string", "constraints": ["string"], "status": "assessed"}

    ### CONSTRAINT
    "compute_required" MUST be exactly one of the lowercase strings "low", "moderate" or "high".
    Emit only that single word - no prose, no explanation, no qualifiers. Put any reasoning about
    compute needs into "constraints" instead.
    """
    subtask_instruction = dspy.InputField(desc="Sub-task instruction for compliance verification")
    assessment_result = dspy.OutputField(desc="JSON block of assessment estimates and constraints")

class SubagentImplementSignature(dspy.Signature):
    """
    ### ROLE
    You are Sub-agent 3: Compliance Verifier.

    ### TASK
    Produce the corrected security configuration for the control gaps you identified during assessment - secure cookies, password policy, MFA, rate limiting, log redaction.

    Build on `prior_assessment` - it is your own earlier analysis of this job, so do
    not re-derive it. If `peer_solutions` is non-empty it holds the combined work of
    the other sub-agents; keep your output consistent with it. If `reviewer_feedback`
    is non-empty, a verifier rejected the previous round - address every point in it.

    ### OUTPUT
    Return the COMPLETE corrected content of every file you touch, not a diff and not
    an excerpt: the manager forwards `modified_files` verbatim as the deliverable.
    Stay concise elsewhere so the files are never truncated.

    ### IMPORTS
    If you modify any source code file, that file must stay runnable on its own. Every
    module, function, class and exception you reference - including names used only in
    `except` clauses, type hints or default arguments (e.g. `binascii.Error`) - must be
    imported or defined in that same file. Add the import for every new name you introduce,
    remove imports you no longer use, and re-read the whole import block against the final
    file before returning it. If a dependency upgrade changes an API, update the affected
    call sites and their imports too.

    Put EXACTLY one JSON block, with no text around it, in the `implementation_result` output field (after `reasoning`): {"agent_role": "Compliance Verifier", "controls_fixed": ["string"], "modified_files": [{"path": "string", "content": "string"}], "residual_risks": ["string"], "status": "completed"}
    """
    subtask_instruction = dspy.InputField(desc="Sub-task instruction, including the source artifacts")
    prior_assessment = dspy.InputField(desc="This agent's own earlier assessment of the same job")
    peer_solutions = dspy.InputField(desc="Combined solutions from the other sub-agents, may be empty")
    reviewer_feedback = dspy.InputField(desc="Required changes from the verifier, may be empty")
    implementation_result = dspy.OutputField(desc="JSON block containing the corrected security configuration")

# --- Sub-Agent Node ---

class SubagentVerifySignature(dspy.Signature):
    """
    ### ROLE
    You are Sub-agent 3: Compliance Verifier, acting as reviewer.

    ### HOW TO REVIEW
    1. FIRST review (`prior_review` is empty): be exhaustive in this single pass. Inspect
       every supplied file, end to end, against the brief and the full OWASP Top 10: injection, broken authentication and session handling, cryptographic failures, secrets in source, vulnerable dependencies, security misconfiguration, logging and monitoring, and plain correctness defects such as missing imports or unreachable code. Build a complete `checklist` and report EVERY issue you can find now,
       including minor ones. Anything already present now but left unreported cannot block
       a later round, so an incomplete first review wastes the whole loop.
    2. LATER reviews (`prior_review` holds your previous verdict): keep the SAME checklist.
       Re-evaluate each earlier item against the new solution and set its status. You may add
       a blocking item ONLY for a defect introduced by the latest changes (origin "regression").
       A problem that already existed in the version you reviewed before goes into
       `advisories`, never into `checklist` or `required_changes`.
    3. Never reverse a requirement you made earlier. If you now think it was wrong, keep the
       item, mark it "pass", and explain why in its evidence - do not demand the opposite.
    4. Stay in scope: every requirement must be achievable by editing the supplied artifacts.
       Do not require code, files, services or integrations that were not supplied.
    5. measured_facts lists the files present, whether each Python file parses and any names a file uses
       without importing or defining them (undefined_names); treat it as ground truth.

    ### VERDICT
    "verdict" is "pass" if and only if every checklist item has status "pass".
    `required_changes` lists one concrete, actionable fix per failing item.

    ### OUTPUT
    Put EXACTLY one JSON block, with no text around it, in the `verification_result` output field (after `reasoning`): {"agent_role": "Compliance Verifier", "verdict": "pass|fail", "checklist": [{"id": "C1", "criterion": "string", "status": "pass|fail", "origin": "brief|regression", "evidence": "string"}], "required_changes": ["string"], "remaining_gaps": ["string"], "advisories": ["string"], "status": "verified"}
    """
    job_description = dspy.InputField(desc="Original brief and source artifacts")
    combined_solution = dspy.InputField(desc="Single merged solution produced by the sub-agents")
    prior_review = dspy.InputField(desc="Your own previous review of this job, empty on the first review")
    measured_facts = dspy.InputField(desc="Facts measured in code by the manager - ground truth")
    verification_result = dspy.OutputField(desc="JSON block with checklist and pass/fail verdict")

class Subagent3SecurityAuditComplianceVerifierAgent:
    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        # Initialize HIS Client
        his_config = getattr(self.subject.persona, 'config', {}).get("parameters", {}).get("HIS_CONFIG", {}) if hasattr(self.subject, 'persona') else {}
        self.his_client = HisClient(
            base_url=his_config.get("HIS_BASE_URL", "http://localhost"),
            poll_interval=his_config.get("HIS_POLL_INTERVAL", 1.0),
            max_wait=his_config.get("HIS_MAX_WAIT", 60)
        )
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        self.task_registry = {}
        self.default_model = "aios:qwen3-1-7b-vllm-block"
        try:
            if self.subject and hasattr(self.subject, 'integrations') and self.subject.integrations and self.subject.integrations.models:
                self.default_model = self.subject.integrations.models[0].llm_block_id
        except Exception:
            pass

    def _get_lm_context(self, model_name, session_id):
        return dspy.settings.context(lm=self.aios_dspy_lm.get_choosen_model(model_name=model_name, session_id=session_id))

    def _predict(self, signature, output_field, **inputs):
        """Run `signature` with chain-of-thought and return the raw text of `output_field`.

        The model sometimes answers with the bare JSON block and skips DSPy's field markers,
        so both adapters raise AdapterParseError although the answer is usable. The raw LM
        response is recovered instead of failing the whole phase; extract_json parses it.
        """
        try:
            return getattr(dspy.ChainOfThought(signature)(**inputs), output_field)
        except AdapterParseError as e:
            log.warning(f"{signature.__name__}: adapter could not parse the LM response; recovering JSON from the raw text")
            raw = e.lm_response or ""
            wrapped = extract_json(raw)
            if isinstance(wrapped, dict) and output_field in wrapped:
                inner = wrapped[output_field]
                return inner if isinstance(inner, str) else json.dumps(inner)
            return raw


    def _registry_put(self, session_id, task_id, kind, instruction, response):
        """Record a phase result as task_registry[session_id][task_id][kind].

        `last_task_id_metadata` is appended in chronological order so a later phase
        can walk it backwards to find the most recent entry of a given kind without
        the caller having to pass that context back in.
        """
        session = self.task_registry.setdefault(session_id, {})
        session.setdefault(task_id, {})[kind] = {
            "instruction": instruction,
            "response": response,
            "status": "assessed" if kind == "assess" else "completed",
        }
        session.setdefault("last_task_id_metadata", []).append(
            {"type": kind, "task_id": task_id}
        )

    def _registry_last(self, session_id, kind):
        """Most recent stored response of `kind` for this session, or {}."""
        session = self.task_registry.get(session_id, {})
        for item in reversed(session.get("last_task_id_metadata", [])):
            if item.get("type") == kind:
                entry = session.get(item.get("task_id"), {}).get(kind, {})
                return entry.get("response", {})
        return {}

    def _log_to_his(self, target_id, job_data):
        try:
            source_id = getattr(self.subject.identity, 'subject_id', 'unknown')
            msg = {"text": str(job_data), "source_id": source_id, "destination_id": target_id, "team": getattr(self, "name", "Agent Team"), "timestamp": time.time()}
            self.his_client.submit(input_data=msg)
        except Exception:
            pass

    def get_muxer(self):
        return None

    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        log.info(f"Preprocessing task {task.task_id} in Subagent3SecurityAuditComplianceVerifier")
        return [task]

    def on_data(self, task: AgentTask) -> AgentResult:

        try:
            # Log incoming request
            self._log_to_his(
                target_id=getattr(self.subject.identity, 'subject_id', 'unknown'),
                job_data={"task_type": "INCOMING_TASK", "payload": task.job_data}
            )
            data = task.job_data
            event_type = data.get("event_type", "assess")
            task_id = data.get("task_id", task.task_id)
            instruction = data.get("text", "")
            model_name = data.get("model_name", self.default_model)
            session_id = data.get("session_id", str(uuid.uuid4()))


            with self._get_lm_context(model_name, session_id):
                if event_type == "assess":
                    raw = self._predict(SubagentAssessSignature, "assessment_result", subtask_instruction=instruction)
                    assess_data = extract_json(raw) or {"can_do": True, "approx_tokens": 1000, "status": "assessed"}
                    self._registry_put(session_id, task_id, "assess", instruction, assess_data)
                    self._log_to_his(target_id=MANAGER_ID, job_data={"task_type": "OUTGOING_RESULT", "payload": assess_data}); return AgentResult(task_id=task_id, job_output=assess_data)

                elif event_type == "implement":
                    # Pull our own last assessment out of the registry rather than
                    # expecting the manager to hand it back.
                    prior_assessment = self._registry_last(session_id, "assess")
                    raw = self._predict(SubagentImplementSignature, "implementation_result",
                        subtask_instruction=instruction,
                        prior_assessment=json.dumps(prior_assessment),
                        peer_solutions=json.dumps(data.get("peer_solutions", {})),
                        reviewer_feedback=json.dumps(data.get("reviewer_feedback", [])),
                    )
                    implement_data = extract_json(raw) or {"agent_role": "Compliance Verifier", "status": "completed"}
                    self._registry_put(session_id, task_id, "implement", instruction, implement_data)
                    self._log_to_his(target_id=MANAGER_ID, job_data={"task_type": "OUTGOING_RESULT", "payload": implement_data}); return AgentResult(task_id=task_id, job_output=implement_data)

                elif event_type == "verify":
                    # Our previous review of this job keeps the checklist fixed across rounds.
                    prior_review = self._registry_last(session_id, "verify")
                    raw = self._predict(SubagentVerifySignature, "verification_result",
                        job_description=instruction,
                        combined_solution=json.dumps(data.get("combined_solution", {})),
                        prior_review=json.dumps(prior_review),
                        measured_facts=json.dumps(data.get("measured_facts", {})),
                    )
                    verify_data = extract_json(raw) or {"agent_role": "Compliance Verifier", "verdict": "fail", "remaining_gaps": ["verifier output could not be parsed"], "required_changes": [], "status": "verified"}
                    self._registry_put(session_id, task_id, "verify", instruction, verify_data)
                    self._log_to_his(target_id=MANAGER_ID, job_data={"task_type": "OUTGOING_RESULT", "payload": verify_data}); return AgentResult(task_id=task_id, job_output=verify_data)

                else:
                    self._log_to_his(target_id=MANAGER_ID, job_data={"task_type": "OUTGOING_RESULT", "payload": {"status": "skipped", "reason": f"unhandled event_type: {event_type}"}}); return AgentResult(task_id=task_id, skip=True)

        except Exception as e:
            log.exception(f"Error in Subagent 3 Compliance Verifier: {e}")
            self._log_to_his(target_id=MANAGER_ID, job_data={"task_type": "OUTGOING_RESULT", "payload": {"status": "error", "message": str(e)}}); return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})

if __name__ == "__main__":
    main(Subagent3SecurityAuditComplianceVerifierAgent)
