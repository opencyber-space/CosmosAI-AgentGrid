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

MANAGER_ID = "manager4-content-creation"


# --- Signatures ---

class SubagentAssessSignature(dspy.Signature):
    """
    ### ROLE
    You are Sub-agent 2: SEO Optimizer.

    ### TASK
    Assess the sub-task instruction for keyword placement, meta description optimization, and search readability scoring. Determine if you can perform this sub-task and estimate token usage, compute requirements, testing environment needs, and any constraints.

    ### OUTPUT
    Output EXACTLY a JSON block: {"can_do": bool, "approx_tokens": int, "compute_required": "low|moderate|high", "testing_env": "string", "constraints": ["string"], "status": "assessed"}

    ### CONSTRAINT
    "compute_required" MUST be exactly one of the lowercase strings "low", "moderate" or "high".
    Emit only that single word - no prose, no explanation, no qualifiers. Put any reasoning about
    compute needs into "constraints" instead.
    """
    subtask_instruction = dspy.InputField(desc="Sub-task instruction for SEO optimization")
    assessment_result = dspy.OutputField(desc="JSON block of assessment estimates and constraints")

class SubagentImplementSignature(dspy.Signature):
    """
    ### ROLE
    You are Sub-agent 2: SEO Optimizer.

    ### TASK
    Produce the SEO-optimised version of the copy, not just a list of suggestions: return the rewritten body with the target keywords worked in at natural density, plus the meta description.

    Build on `prior_assessment` - your own earlier analysis of this job. If
    `peer_solutions` is non-empty it holds the other sub-agents' work; build on their
    copy rather than starting over. If `reviewer_feedback` is non-empty the editor
    rejected the previous round - address every point.

    ### OUTPUT
    Return ONE complete article, not an excerpt, a diff or a description of changes.

    ### FORMAT RULES
    - Put the article (H1, H2 sections, prose, CTA) in "optimized_content" as Markdown.
    - Put the meta description ONLY in "meta_description". Never write a
      "Meta description:" line inside the article.
    - If `peer_solutions` has an "article", revise THAT text - do not start a new draft.
    - Length is measured in code by the manager, so do not report a word count:
        * article length = WORDS of prose only (headings and the meta description are
          excluded from the count);
        * meta description length = CHARACTERS, not words.
      `reviewer_feedback` carries the exact numbers measured last round - use them to
      add or cut the right amount.

    Put EXACTLY one JSON block, with no text around it, in the `implementation_result` output field (after `reasoning`): {"agent_role": "SEO Optimizer", "optimized_content": "string", "keywords_added": ["string"], "meta_description": "string", "seo_score": "string", "status": "completed"}
    """
    subtask_instruction = dspy.InputField(desc="Sub-task instruction, including the source draft")
    prior_assessment = dspy.InputField(desc="This agent's own earlier assessment of the same job")
    peer_solutions = dspy.InputField(desc="Combined work from the other sub-agents, may be empty")
    reviewer_feedback = dspy.InputField(desc="Required changes from the editor, may be empty")
    implementation_result = dspy.OutputField(desc="JSON block containing the SEO-optimised copy")

# --- Sub-Agent Node ---

class SubagentVerifySignature(dspy.Signature):
    """
    ### ROLE
    You are Sub-agent 2: SEO Optimizer, acting as editor-in-chief.

    ### HOW TO REVIEW
    1. FIRST review (`prior_review` is empty): be exhaustive in this single pass. Inspect
       the whole article against every line of the brief: length, H1 and H2 structure, meta description, keyword coverage and density, internal CTA, grammar, spelling and tone. Build a complete `checklist` and report EVERY issue you can find now,
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
    5. measured_facts holds counts computed in code: article body WORDS (prose only - headings and the meta description excluded), meta_description CHARACTERS, H1/H2 counts and keyword density. Use those numbers verbatim; never estimate a count yourself, and never say a count is unverifiable.

    ### VERDICT
    "verdict" is "pass" if and only if every checklist item has status "pass".
    `required_changes` lists one concrete, actionable fix per failing item.

    ### OUTPUT
    Put EXACTLY one JSON block, with no text around it, in the `verification_result` output field (after `reasoning`): {"agent_role": "SEO Optimizer", "verdict": "pass|fail", "checklist": [{"id": "C1", "criterion": "string", "status": "pass|fail", "origin": "brief|regression", "evidence": "string"}], "required_changes": ["string"], "remaining_gaps": ["string"], "advisories": ["string"], "status": "verified"}
    """
    job_description = dspy.InputField(desc="Original brief and source artifacts")
    combined_solution = dspy.InputField(desc="Single merged solution produced by the sub-agents")
    prior_review = dspy.InputField(desc="Your own previous review of this job, empty on the first review")
    measured_facts = dspy.InputField(desc="Facts measured in code by the manager - ground truth")
    verification_result = dspy.OutputField(desc="JSON block with checklist and pass/fail verdict")

class Subagent2ContentCreationSeoOptimizerAgent:
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
        """Record a phase result as task_registry[session_id][task_id][kind]."""
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
        log.info(f"Preprocessing task {task.task_id} in Subagent2ContentCreationSeoOptimizer")
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
                    assess_data = extract_json(raw) or {"can_do": True, "approx_tokens": 1100, "status": "assessed"}
                    self._registry_put(session_id, task_id, "assess", instruction, assess_data)
                    self._log_to_his(target_id=MANAGER_ID, job_data={"task_type": "OUTGOING_RESULT", "payload": assess_data}); return AgentResult(task_id=task_id, job_output=assess_data)

                elif event_type == "implement":
                    prior_assessment = self._registry_last(session_id, "assess")
                    raw = self._predict(SubagentImplementSignature, "implementation_result",
                        subtask_instruction=instruction,
                        prior_assessment=json.dumps(prior_assessment),
                        peer_solutions=json.dumps(data.get("peer_solutions", {})),
                        reviewer_feedback=json.dumps(data.get("reviewer_feedback", [])),
                    )
                    implement_data = extract_json(raw) or {"agent_role": "SEO Optimizer", "optimized_content": "", "status": "completed"}
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
                    verify_data = extract_json(raw) or {"agent_role": "SEO Optimizer", "verdict": "fail", "remaining_gaps": ["verifier output could not be parsed"], "required_changes": [], "status": "verified"}
                    self._registry_put(session_id, task_id, "verify", instruction, verify_data)
                    self._log_to_his(target_id=MANAGER_ID, job_data={"task_type": "OUTGOING_RESULT", "payload": verify_data}); return AgentResult(task_id=task_id, job_output=verify_data)

                else:
                    self._log_to_his(target_id=MANAGER_ID, job_data={"task_type": "OUTGOING_RESULT", "payload": {"status": "skipped", "reason": f"unhandled event_type: {event_type}"}}); return AgentResult(task_id=task_id, skip=True)

        except Exception as e:
            log.exception(f"Error in Subagent 2 SEO Optimizer: {e}")
            self._log_to_his(target_id=MANAGER_ID, job_data={"task_type": "OUTGOING_RESULT", "payload": {"status": "error", "message": str(e)}}); return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})

if __name__ == "__main__":
    main(Subagent2ContentCreationSeoOptimizerAgent)
