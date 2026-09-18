import logging
import time
from agents_sdk.core.his import HisClient
import uuid
import json
import re
import dspy
from typing import Any, Dict, List, Optional

from agents_sdk.core.agent_executor import AgentTask, AgentResult, Context
from agents_sdk.core.main import main
from agents_sdk.core.known_agents import KnownAgents
import os
from openarcade_bidding_pysdk.client import OpenarcadeClient
from utils.dspy_aios_llms import AIOS_DSPy_LMs
from utils.json_utils import extract_json

log = logging.getLogger(__name__)

# Reserved key inside task_registry (sits alongside session_id keys).
BID_JOB_INDEX = "bid_job_index"

# --- 1. Signatures ---

class QualificationSignature(dspy.Signature):
    """
    ### ROLE
    You are Manager for Content Creation.

    ### TASK
    Assess whether the incoming job request falls within Copywriting, Blog/Article Drafting, SEO Keyword Optimization, Meta Description Generation, or Editorial Proofreading.
    If the job is too broad, explicitly identify the portion of the job that is out of scope.

    ### OUTPUT
    Output EXACTLY a JSON block: {"is_qualified": bool, "reasoning": "string", "out_of_scope": "string"}
    """
    job_description = dspy.InputField(desc="Incoming job request description")
    domain_fields_of_interest = dspy.InputField(desc="Domain fields of interest for Content Creation")
    qualification_result = dspy.OutputField(desc='JSON block: {"is_qualified": bool, "reasoning": "string", "out_of_scope": "string"}')

class TaskBreakdownSignature(dspy.Signature):
    """
    ### ROLE
    You are Manager 4 for Content Creation.

    ### TASK
    Decompose the qualified content creation job into sub-tasks for available subordinate agents (copywriter, SEO optimizer, proofreader editor).

    ### OUTPUT
    Output EXACTLY a JSON block mapping subordinate agent ID to sub-task instructions:
    {"subtask_assignments": [{"agent_id": "string", "instruction": "string"}]}
    """
    job_description = dspy.InputField(desc="Content creation job description")
    subordinates_info = dspy.InputField(desc="List of available subordinate agents and their capabilities")
    breakdown_result = dspy.OutputField(desc='JSON block with subtask_assignments')

class BidAggregationSignature(dspy.Signature):
    """
    ### ROLE
    You are Manager 4 for Content Creation.

    ### TASK
    Aggregate assessment estimates and constraints received from content creation sub-agents into a consolidated bid proposal.

    ### OUTPUT
    Output EXACTLY a JSON block: {"manager_id": "string", "total_estimated_tokens": int, "required_compute": "low|moderate|high", "testing_env": "string", "proposed_timeline": "fast|medium|slow", "aggregated_constraints": ["string"], "bid_status": "submitted"}

    ### CONSTRAINT
    "required_compute" MUST be exactly one of the lowercase strings "low", "moderate" or "high"
    (the highest tier reported by any sub-agent).
    "proposed_timeline" MUST be exactly one of the lowercase strings "fast", "medium" or "slow"
    (the slowest pace reported by any sub-agent).
    Emit only those single words - no prose, no durations such as "1-2 business days", no
    qualifiers. Put any reasoning into "aggregated_constraints" instead. "required_compute" is
    consumed by the bid evaluator as a numeric tier, so any other text makes the bid unscoreable.
    """
    job_description = dspy.InputField(desc="Content creation job description")
    subagent_assessments = dspy.InputField(desc="Sub-agent constraint and estimation responses")
    bid_result = dspy.OutputField(desc="JSON block containing aggregated bid metrics")

class ImplementationRoutingSignature(dspy.Signature):
    """
    ### ROLE
    You are Manager 4 for Content Creation, planning one round of the implementation phase.

    ### TASK
    Decide which sub-agents should implement this round and which should review the
    clubbed result. You may route partially: it is valid to have only some sub-agents
    implement while another reviews, and on a later round to send the combined solution
    back to the implementers as well so they confirm it still holds.

    ### OWNERSHIP RULE
    Every artifact the job touches must have an implementer who owns it this round.
    A reviewer does not produce work, so if the only agent competent for some artifact
    is acting as reviewer, either assign that artifact to another implementer or move
    that agent into `implementers` and pick a different reviewer. Leaving an artifact
    unowned wastes a round: the reviewer will simply reject it as unaddressed.

    Use only agent ids present in `subordinates`. On round 1 there is no prior verdict;
    on later rounds `prior_verdict` says what failed, so route to whoever can fix it.

    ### OUTPUT
    Output EXACTLY a JSON block: {"implementers": ["string"], "verifiers": ["string"], "reasoning": "string"}
    """
    job_description = dspy.InputField(desc="Content creation job description")
    subordinates = dspy.InputField(desc="Available sub-agent ids")
    round_no = dspy.InputField(desc="1-based index of this implementation round")
    prior_verdict = dspy.InputField(desc="Verifier verdict from the previous round, empty on round 1")
    routing_result = dspy.OutputField(desc="JSON block naming implementers and verifiers")


class ExecutionAggregationSignature(dspy.Signature):
    """
    ### ROLE
    You are Manager 4 for Content Creation.

    ### TASK
    Synthesize implementation results from all content sub-agents into a final Content Delivery Report.

    ### OUTPUT
    Take every count (words, characters, densities) from verification.measured_facts -
    never estimate or restate a target as if it were achieved. Report the final verdict honestly.

    Output EXACTLY a JSON block: {"content_summary": "string", "articles_written": ["string"], "seo_score": "string", "overall_status": "completed"}
    """
    job_description = dspy.InputField(desc="Content creation job description")
    subagent_results = dspy.InputField(desc="Execution results from content creation sub-agents")
    verification = dspy.InputField(desc="Final verifier verdict and any remaining gaps")
    final_report = dspy.OutputField(desc="JSON block of final content delivery")

# --- 2. Manager Agent Node ---

class Manager4ContentCreationAgent:
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
        self.persona_default_system_message = self.subject.persona.default_system_message
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        self.default_model = "aios:qwen3-1-7b-vllm-block"
        try:
            if self.subject and hasattr(self.subject, 'integrations') and self.subject.integrations and self.subject.integrations.models:
                self.default_model = self.subject.integrations.models[0].llm_block_id
        except Exception:
            pass
        self.task_registry = {}

        # Discover content creation sub-agents
        try:
            known_agents = KnownAgents(default_compact=False)
            known_agents.query_and_add(query={
                "metadata.subject_search_tags": "content-creation-subordinates"
            })
            self.subordinates = [agent.id for agent in known_agents.list_all()]
            log.info("Manager 4 discovered content creation subordinates: %s", self.subordinates)
        except Exception as e:
            log.error(f"Failed to discover content creation subordinates: {e}")
            self.subordinates = []

    def _get_lm_context(self, model_name, session_id):
        return dspy.settings.context(lm=self.aios_dspy_lm.get_choosen_model(model_name=model_name, session_id=session_id))

    def _init_task(self, session_id, task_id, user_request=None):
        """Ensure task_registry[session_id][task_id] exists and return it."""
        session = self.task_registry.setdefault(session_id, {})
        if task_id not in session:
            session[task_id] = {
                "user_request": user_request,
                "assess_responses": {},
                "implement_responses": {},
                "subtasks": []
            }
        return session[task_id]

    def _task_entry(self, session_id, task_id):
        """task_registry[session_id][task_id], created on demand."""
        return self.task_registry.setdefault(session_id, {}).setdefault(task_id, {})


    def _index_bid_job(self, bid_job_id, session_id, task_id):
        """Remember which session/task a bid_job belongs to.

        A bid_winner notification carries only bid_job_id - no session_id and no
        task_id - so without this index the winner hop would mint a fresh session
        and lose everything cached during the bid phase.
        """
        if not bid_job_id:
            return
        index = self.task_registry.setdefault(BID_JOB_INDEX, {})
        index[bid_job_id] = {"session_id": session_id, "task_id": task_id}

    def _lookup_bid_job(self, bid_job_id):
        """(session_id, task_id) recorded for this bid_job, or (None, None)."""
        if not bid_job_id:
            return None, None
        record = self.task_registry.get(BID_JOB_INDEX, {}).get(bid_job_id) or {}
        return record.get("session_id"), record.get("task_id")

    def _log_to_his(self, target_id, job_data):
        try:
            source_id = getattr(self.subject.identity, 'subject_id', 'unknown')
            msg = {"text": str(job_data), "source_id": source_id, "destination_id": target_id, "team": getattr(self, "name", "Agent Team"), "timestamp": time.time()}
            self.his_client.submit(input_data=msg)
        except Exception:
            pass

    def _submit_to_openarcade(self, bid_job_id, bid_data):
        if bid_job_id:
            try:
                base_url = os.environ.get("OPENARCADE_BIDDING_URL", "http://localhost:5000")
                client = OpenarcadeClient(base_url=base_url)
                agent_name = getattr(self.subject.identity, "subject_id", None) or os.environ.get("SUBJECT_ID")
                if not agent_name:
                    raise ValueError("Unable to resolve subject_id for bid submission")
                client.submit_bid(
                    bid_job_id=bid_job_id,
                    bid_subject_id=agent_name,
                    bid_data=bid_data
                )
                log.info(f"Successfully submitted bid for {bid_job_id} using SDK.")
            except Exception as e:
                log.error(f"Failed to submit bid via SDK: {e}")
        else:
            log.warning("No bid_job_id found in task payload, skipping SDK submission.")

    def get_muxer(self):
        return None

    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        log.info(f"Preprocessing task {task.task_id} in Manager4ContentCreation")
        return [task]

    def on_data(self, task: AgentTask) -> AgentResult:

        try:
            # Log incoming request
            self._log_to_his(
                target_id=getattr(self.subject.identity, 'subject_id', 'unknown'),
                job_data={"task_type": "INCOMING_TASK", "payload": task.job_data}
            )
            data = task.job_data
            event_type = data.get("type", data.get("event_type", "bid_request"))
            task_id = data.get("task_id", task.task_id)
            bid_job_id = data.get("bid_job_id") or data.get("bid_job", {}).get("bid_job_id")
            user_request = data.get("bid_job", {}).get("bid_job_description", {}).get("text", data.get("text", ""))
            communication_type = data.get("communication_type", "p2p")
            model_name = data.get("model_name", self.default_model)
            session_id = data.get("session_id", str(uuid.uuid4()))

            # A bid_winner notification is deliberately lean: it carries neither the
            # bid_job nor the originating task_id (see delegate-system docs 5.3). Recover
            # the context cached during bid_request so sub-agents get the real job spec.
            if event_type == "bid_winner":
                prior_session_id, prior_task_id = self._lookup_bid_job(bid_job_id)
                if prior_task_id:
                    task_id = prior_task_id
                    # Reuse the bid-phase session so sub-agents can still read the
                    # assessments they stored under it.
                    session_id = prior_session_id or session_id
                    user_request = self._task_entry(session_id, task_id).get("user_request") or user_request
                else:
                    log.warning(f"No cached bid_request context for bid_job_id {bid_job_id}")

            self._init_task(session_id, task_id, user_request)
            if bid_job_id:
                self._task_entry(session_id, task_id)["bid_job_id"] = bid_job_id
                self._index_bid_job(bid_job_id, session_id, task_id)
            # Keep the structured job spec (acceptance criteria) from bid_request; the
            # bid_winner hop does not carry it, so the implementation phase reads it back.
            job_spec = data.get("bid_job", {}).get("bid_job_description")
            if isinstance(job_spec, dict) and job_spec:
                self._task_entry(session_id, task_id)["bid_job_description"] = job_spec

            if event_type == "bid_request":
                return self._handle_bid_request(task, task_id, user_request, session_id, model_name, communication_type)
            elif event_type in ("bid_winner", "bid_response"):
                return self._handle_bid_response(task, task_id, user_request, session_id, model_name, communication_type)
            else:
                log.warning(f"Unknown event_type {event_type} in Manager 4")
                self._log_to_his(target_id="USER_OR_NEXT", job_data={"task_type": "OUTGOING_RESULT", "payload": {"status": "skipped", "reason": f"unhandled event_type: {event_type}"}}); return AgentResult(task_id=task.task_id, skip=True)

        except Exception as e:
            log.exception(f"Error in Manager 4 Content Creation Agent: {e}")
            self._log_to_his(target_id="USER_OR_NEXT", job_data={"task_type": "OUTGOING_RESULT", "payload": {"status": "error", "message": str(e)}}); return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})

    def _handle_bid_request(self, task, task_id, job_desc, session_id, model_name, comm_type):
        with self._get_lm_context(model_name, session_id):
            qual_module = dspy.ChainOfThought(QualificationSignature)
            domain_interest = "Copywriting, Article Drafting, Blog Posts, SEO Optimization, Keyword Density, Meta Descriptions, Proofreading, Tone Editing, Editorial Review"
            qual_res = qual_module(job_description=job_desc, domain_fields_of_interest=domain_interest)
            qual_data = extract_json(qual_res.qualification_result) or {}

            if isinstance(qual_data, dict) and not qual_data.get("is_qualified", True):
                log.info(f"Manager 4 declined job {task_id}: {qual_data.get('reasoning')}")
                bid_data = {
                    "status": "declined",
                    "reason": qual_data.get("reasoning"),
                    "total_estimated_tokens": 9007199254740991,
                    "required_compute": 9007199254740991,
                    "bid_status": "declined"
                }
                bid_job_id = task.job_data.get("bid_job_id")
                self._submit_to_openarcade(bid_job_id, bid_data)
                self._log_to_his(target_id="USER_OR_NEXT", job_data={"task_type": "OUTGOING_RESULT", "payload": bid_data})
                return AgentResult(task_id=task_id, job_output=bid_data)

            breakdown_module = dspy.ChainOfThought(TaskBreakdownSignature)
            breakdown_res = breakdown_module(job_description=job_desc, subordinates_info=json.dumps(self.subordinates))
            breakdown_data = extract_json(breakdown_res.breakdown_result) or {}
            assignments = breakdown_data.get("subtask_assignments", []) if isinstance(breakdown_data, dict) else []

        assess_responses = {}
        for sub_id in self.subordinates:
            instruction = f"Assess content creation sub-task for {sub_id}"
            for assign in assignments:
                if assign.get("agent_id") == sub_id:
                    instruction = assign.get("instruction", instruction)

            sub_job_data = {
                "event_type": "assess",
                "text": instruction,
                "session_id": session_id,
                "model_name": model_name,
                "communication_type": comm_type,
                "task_id": task_id
            }

            if comm_type == "p2p":
                res = self.context.p2p_manager.send_and_wait_sync(task_id=task_id, subject_id=sub_id, task_data=sub_job_data)
                assess_responses[sub_id] = res.get("data", {})
            elif comm_type == "delegate":
                res = self.context.delegator.submit_and_wait(subject_id=sub_id, session_id=session_id, task_id=task_id, task_data=sub_job_data)
                assess_responses[sub_id] = res
            else:
                self.context.direct.submit(to=sub_id, session_id=session_id, task=task, job_data=sub_job_data)
                assess_responses[sub_id] = {"status": "dispatched"}

        self._task_entry(session_id, task_id)["assess_responses"] = assess_responses

        with self._get_lm_context(model_name, session_id):
            agg_module = dspy.ChainOfThought(BidAggregationSignature)
            agg_res = agg_module(job_description=job_desc, subagent_assessments=json.dumps(assess_responses))
            bid_data = extract_json(agg_res.bid_result) or {}

        self._task_entry(session_id, task_id)["bid_data"] = bid_data
        self._task_entry(session_id, task_id)["qual_data"] = qual_data
        self._task_entry(session_id, task_id)["breakdown_data"] = breakdown_data
        
        # OpenArcade SDK Submission
        bid_job_id = task.job_data.get("bid_job_id")
        self._submit_to_openarcade(bid_job_id, bid_data)

        self._log_to_his(target_id="USER_OR_NEXT", job_data={"task_type": "OUTGOING_RESULT", "payload": bid_data}); return AgentResult(task_id=task_id, job_output=bid_data)

    MAX_APPROVAL_LOOPS = 3
    VERIFIER_HINTS = ("compliance", "vrf", "verifier", "proofreader", "editor", "reviewer")

    def _dispatch(self, sub_id, task, task_id, session_id, comm_type, sub_job_data):
        """Send one task to a sub-agent over the configured transport."""
        if comm_type == "p2p":
            res = self.context.p2p_manager.send_and_wait_sync(task_id=task_id, subject_id=sub_id, task_data=sub_job_data)
            return res.get("data", {})
        if comm_type == "delegate":
            return self.context.delegator.submit_and_wait(subject_id=sub_id, session_id=session_id, task_id=task_id, task_data=sub_job_data)
        self.context.direct.submit(to=sub_id, session_id=session_id, task=task, job_data=sub_job_data)
        return {"status": "dispatched"}

    def _plan_round(self, job_desc, session_id, model_name, round_no, prior_verdict):
        """Ask the LLM who implements and who reviews, then sanity-check the answer."""
        implementers, verifiers = [], []
        try:
            with self._get_lm_context(model_name, session_id):
                route_res = dspy.ChainOfThought(ImplementationRoutingSignature)(
                    job_description=job_desc,
                    subordinates=json.dumps(self.subordinates),
                    round_no=str(round_no),
                    prior_verdict=json.dumps(prior_verdict or {}),
                )
            plan = extract_json(route_res.routing_result) or {}
            implementers = [s for s in plan.get("implementers", []) if s in self.subordinates]
            verifiers = [s for s in plan.get("verifiers", []) if s in self.subordinates]
        except Exception as e:
            log.warning(f"Routing generation failed, using role defaults: {e}")

        if not implementers or not verifiers:
            verifiers = [s for s in self.subordinates if any(h in s for h in self.VERIFIER_HINTS)]
            implementers = [s for s in self.subordinates if s not in verifiers]
            if not verifiers and self.subordinates:
                verifiers = [self.subordinates[-1]]
                implementers = [s for s in self.subordinates if s not in verifiers]
            log.info(f"Round {round_no} routing fell back to defaults: impl={implementers} verify={verifiers}")

        return implementers, verifiers

    @staticmethod
    def _job_output(res):
        """Strip the transport envelope and return the agent's own job_output."""
        if isinstance(res, dict) and isinstance(res.get("job_output"), dict):
            return res["job_output"]
        return res if isinstance(res, dict) else {}

    ARTICLE_FIELDS = ("edited_content", "optimized_content", "draft_content", "article")
    WORD_RE = r"[A-Za-z0-9][A-Za-z0-9'\u2019-]*"

    @staticmethod
    def _new_solution():
        return {"article": "", "meta_description": "", "contributions": {}}

    @staticmethod
    def _split_meta(article):
        """Pull a stray 'Meta description:' line out of the article body."""
        meta, kept = "", []
        for line in article.splitlines():
            m = re.match(r"^\s*[*_]*\s*meta description\s*[*_]*\s*:\s*(.*)$", line, re.I)
            if m and not meta:
                meta = m.group(1).strip()
            else:
                kept.append(line)
        return "\n".join(kept).strip(), meta

    def _merge_into(self, merged, sub_id, out):
        """Fold one implementer's output into the single article the verifier sees.

        Every content implementer edits the same article, so the newest non-empty version
        replaces the previous one rather than sitting beside it as a rival draft.
        """
        article = next((out[f] for f in self.ARTICLE_FIELDS
                        if isinstance(out.get(f), str) and out[f].strip()), "")
        inline_meta = ""
        if article:
            article, inline_meta = self._split_meta(article)
            merged["article"] = article
        meta = out.get("meta_description")
        meta = meta.strip() if isinstance(meta, str) and meta.strip() else inline_meta
        if meta:
            merged["meta_description"] = meta
        merged["contributions"][sub_id] = {k: v for k, v in out.items()
                                           if k not in self.ARTICLE_FIELDS and k != "meta_description"}

    def _measure_solution(self, merged, criteria, job_desc=""):
        """Counts computed in code and checked against the job's acceptance criteria.

        Article words count prose only: headings and the meta description are excluded.
        The meta description is measured in characters.
        """
        article = merged.get("article") or ""
        meta = merged.get("meta_description") or ""
        lines = article.splitlines()
        headings = [l for l in lines if re.match(r"^\s*#{1,6}\s", l)]
        prose = "\n".join(l for l in lines if l.strip() and l not in headings)
        body_words = len(re.findall(self.WORD_RE, prose))
        all_words = len(re.findall(self.WORD_RE, article))
        h1 = sum(1 for l in headings if re.match(r"^\s*#\s", l))
        h2 = sum(1 for l in headings if re.match(r"^\s*##\s", l))

        density = {}
        lowered = article.lower()
        for kw in criteria.get("keywords") or []:
            hits = len(re.findall(r"(?<![a-z0-9])" + re.escape(kw.lower()) + r"(?![a-z0-9])", lowered))
            kw_words = len(re.findall(self.WORD_RE, kw)) or 1
            density[kw] = {"occurrences": hits,
                           "density_pct": round(100.0 * hits * kw_words / all_words, 2) if all_words else 0.0}

        facts = {
            "article_body_words": body_words,
            "article_body_words_rule": "prose only; headings and the meta description are excluded",
            "meta_description_characters": len(meta),
            "meta_description_words": len(re.findall(self.WORD_RE, meta)),
            "h1_count": h1,
            "h2_count": h2,
            "keyword_density": density,
        }

        hard = []
        if not article.strip():
            hard.append("No article was produced - return the full article.")
        lo, hi = criteria.get("body_words_min"), criteria.get("body_words_max")
        if lo is not None and hi is not None and not lo <= body_words <= hi:
            verb = "Add" if body_words < lo else "Cut"
            hard.append(f"Article body is {body_words} words; it must be {lo}-{hi} words "
                        f"(prose only - headings and the meta description do not count). "
                        f"{verb} about {abs((lo + hi) // 2 - body_words)} words.")
        max_chars = criteria.get("meta_description_max_chars")
        if max_chars is not None:
            if not meta:
                hard.append("meta_description is missing - return it in the meta_description field, not inside the article.")
            elif len(meta) > max_chars:
                hard.append(f"meta_description is {len(meta)} characters; it must be at most {max_chars} characters. "
                            f"Remove about {len(meta) - max_chars} characters.")
        if criteria.get("h1_count") is not None and h1 != criteria["h1_count"]:
            hard.append(f"Article has {h1} H1 headings; it must have exactly {criteria['h1_count']}.")
        if criteria.get("h2_min") is not None and h2 < criteria["h2_min"]:
            hard.append(f"Article has {h2} H2 sections; it needs at least {criteria['h2_min']}.")
        for kw, d in density.items():
            if d["occurrences"] == 0:
                hard.append(f"Target keyword '{kw}' does not appear in the article.")
        return facts, hard

    @staticmethod
    def _deliverable(merged):
        return {"article": merged.get("article", ""), "meta_description": merged.get("meta_description", "")}

    def _handle_bid_response(self, task, task_id, job_desc, session_id, model_name, comm_type):
        log.info(f"Manager 4 won bid for task {task_id}. Starting implementation phase...")
        entry = self._task_entry(session_id, task_id)
        criteria = (entry.get("bid_job_description") or {}).get("acceptance_criteria") or {}

        merged = self._new_solution()
        verification = {}
        reviewer_feedback = []
        advisories = []
        facts = {}
        approval_loops = 0
        reviewed_before = set()     # verifiers that have already reviewed this job

        for round_no in range(1, self.MAX_APPROVAL_LOOPS + 1):
            approval_loops = round_no
            implementers, verifiers = self._plan_round(job_desc, session_id, model_name, round_no, verification)
            log.info(f"Round {round_no}: implementers={implementers} verifiers={verifiers}")

            # --- implement: everyone revises the single merged solution ---
            for sub_id in implementers:
                raw = self._dispatch(sub_id, task, task_id, session_id, comm_type, {
                    "event_type": "implement",
                    "text": f"Implement content creation sub-task for {job_desc}",
                    "session_id": session_id,
                    "model_name": model_name,
                    "communication_type": comm_type,
                    "task_id": task_id,
                    "peer_solutions": merged,
                    "reviewer_feedback": reviewer_feedback,
                })
                self._merge_into(merged, sub_id, self._job_output(raw))

            # --- measure what the model must not be trusted to count ---
            facts, hard_failures = self._measure_solution(merged, criteria, job_desc)

            # --- verify: the critic judges one artifact, with measured facts ---
            verify_results = {}
            for sub_id in verifiers:
                verify_results[sub_id] = self._job_output(self._dispatch(sub_id, task, task_id, session_id, comm_type, {
                    "event_type": "verify",
                    "text": job_desc,
                    "session_id": session_id,
                    "model_name": model_name,
                    "communication_type": comm_type,
                    "task_id": task_id,
                    "combined_solution": merged,
                    "measured_facts": facts,
                }))

            required = []
            verifier_pass = bool(verify_results)
            for sub_id, out in verify_results.items():
                failing = [i for i in (out.get("checklist") or [])
                           if isinstance(i, dict) and str(i.get("status", "")).lower() != "pass"]
                said_pass = str(out.get("verdict", "fail")).lower() == "pass"
                if not said_pass or failing:
                    verifier_pass = False
                required.extend(str(r) for r in (out.get("required_changes") or []))
                if said_pass and failing:
                    # A "pass" that contradicts its own checklist is not a pass.
                    required.extend(f"{i.get('id', '')} {i.get('criterion', '')}".strip() for i in failing)
                raised = [str(a) for a in (out.get("advisories") or []) if a]
                if sub_id in reviewed_before:
                    # Returning reviewer: an issue it missed earlier stays non-blocking.
                    advisories.extend(a for a in raised if a not in advisories)
                elif raised:
                    # First review: there is no earlier round it could have missed these in,
                    # so an "advisory" here is an issue being waved through - make it block.
                    verifier_pass = False
                    required.extend(raised)
            reviewed_before.update(verify_results)

            # Measured failures override any verdict: a count the model got wrong cannot pass.
            passed = verifier_pass and not hard_failures
            reviewer_feedback = list(dict.fromkeys(hard_failures + required))
            verification = {
                "round": round_no,
                "verdict": "pass" if passed else "fail",
                "verifier_verdicts": {k: v.get("verdict") for k, v in verify_results.items()},
                "measured_facts": facts,
                "hard_failures": hard_failures,
                "required_changes": reviewer_feedback,
            }

            entry["approval_loops"] = approval_loops
            entry[f"round_{round_no}"] = {
                "implementers": implementers, "verifiers": verifiers, "verdict": verification["verdict"],
                "hard_failures": hard_failures, "measured_facts": facts, "verifier_outputs": verify_results,
            }

            if passed:
                log.info(f"Verifier approved on round {round_no}; returning to caller.")
                break
            log.info(f"Round {round_no} rejected: {reviewer_feedback}")

        with self._get_lm_context(model_name, session_id):
            final_res = dspy.ChainOfThought(ExecutionAggregationSignature)(
                job_description=job_desc,
                subagent_results=json.dumps(merged),
                verification=json.dumps(verification),
            )
            final_report = extract_json(final_res.final_report) or {}

        final_report["approval_loops"] = approval_loops
        final_report["verification_verdict"] = verification.get("verdict", "fail")
        final_report["measured_facts"] = facts
        final_report["advisories"] = advisories
        final_report["deliverable"] = self._deliverable(merged)

        entry["implement_responses"] = merged
        entry["final_report"] = final_report
        self._log_to_his(target_id="USER_OR_NEXT", job_data={"task_type": "OUTGOING_RESULT", "payload": final_report}); return AgentResult(task_id=task_id, job_output=final_report)


if __name__ == "__main__":
    main(Manager4ContentCreationAgent)
