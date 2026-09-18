import logging
import time
from agents_sdk.core.his import HisClient
import uuid
import json
import ast
import builtins
import re
import yaml
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
    You are Manager for Security & Audit.

    ### TASK
    Assess whether the incoming job request falls within the domain of Security, Vulnerability Auditing, Code Scanning, Dependency Analysis, or Regulatory Compliance.
    If the job is too broad, explicitly identify the portion of the job that is out of scope.

    ### OUTPUT
    Output EXACTLY a JSON block: {"is_qualified": bool, "reasoning": "string", "out_of_scope": "string"}
    """
    job_description = dspy.InputField(desc="Incoming job request description")
    domain_fields_of_interest = dspy.InputField(desc="Domain fields of interest for Security & Audit")
    qualification_result = dspy.OutputField(desc='JSON block: {"is_qualified": bool, "reasoning": "string", "out_of_scope": "string"}')

class TaskBreakdownSignature(dspy.Signature):
    """
    ### ROLE
    You are Manager 1 for Security & Audit.

    ### TASK
    Decompose the qualified security audit job into specific sub-tasks for available subordinate agents.
    Match sub-tasks to subordinate agent IDs based on their capabilities (e.g. SAST scanning, CVE dependency checking, compliance verification).

    ### OUTPUT
    Output EXACTLY a JSON block mapping subordinate agent ID to sub-task instructions:
    {"subtask_assignments": [{"agent_id": "string", "instruction": "string"}]}
    """
    job_description = dspy.InputField(desc="Security audit job description")
    subordinates_info = dspy.InputField(desc="List of available subordinate agents and their capabilities")
    breakdown_result = dspy.OutputField(desc='JSON block with subtask_assignments')

class BidAggregationSignature(dspy.Signature):
    """
    ### ROLE
    You are Manager 1 for Security & Audit.

    ### TASK
    Aggregate assessment estimates and constraints received from security sub-agents into a consolidated bid proposal.

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
    job_description = dspy.InputField(desc="Security audit job description")
    subagent_assessments = dspy.InputField(desc="Sub-agent constraint and estimation responses")
    bid_result = dspy.OutputField(desc="JSON block containing aggregated bid metrics")

class ImplementationRoutingSignature(dspy.Signature):
    """
    ### ROLE
    You are Manager 1 for Security & Audit, planning one round of the implementation phase.

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
    job_description = dspy.InputField(desc="Security audit job description")
    subordinates = dspy.InputField(desc="Available sub-agent ids")
    round_no = dspy.InputField(desc="1-based index of this implementation round")
    prior_verdict = dspy.InputField(desc="Verifier verdict from the previous round, empty on round 1")
    routing_result = dspy.OutputField(desc="JSON block naming implementers and verifiers")


class ExecutionAggregationSignature(dspy.Signature):
    """
    ### ROLE
    You are Manager 1 for Security & Audit.

    ### TASK
    Synthesize implementation results from all security sub-agents into a final Security Audit Report.

    ### OUTPUT
    Take every count (words, characters, densities) from verification.measured_facts -
    never estimate or restate a target as if it were achieved. Report the final verdict honestly.

    Output EXACTLY a JSON block: {"audit_summary": "string", "vulnerabilities_found": ["string"], "compliance_status": "string", "overall_status": "completed"}
    """
    job_description = dspy.InputField(desc="Security audit job description")
    subagent_results = dspy.InputField(desc="Execution results from security sub-agents")
    verification = dspy.InputField(desc="Final verifier verdict and any remaining gaps")
    final_report = dspy.OutputField(desc="JSON block of final audit delivery")

# --- 2. Manager Agent Node ---

class Manager1SecurityAuditAgent:
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

        # Discover security sub-agents
        try:
            known_agents = KnownAgents(default_compact=False)
            known_agents.query_and_add(query={
                "metadata.subject_search_tags": "security-subordinates"
            })
            self.subordinates = [agent.id for agent in known_agents.list_all()]
            log.info("Manager 1 discovered security subordinates: %s", self.subordinates)
        except Exception as e:
            log.error(f"Failed to discover security subordinates: {e}")
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
        log.info(f"Preprocessing task {task.task_id} in Manager1SecurityAudit")
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
                log.warning(f"Unknown event_type {event_type} in Manager 1")
                self._log_to_his(target_id="USER_OR_NEXT", job_data={"task_type": "OUTGOING_RESULT", "payload": {"status": "skipped", "reason": f"unhandled event_type: {event_type}"}}); return AgentResult(task_id=task.task_id, skip=True)

        except Exception as e:
            log.exception(f"Error in Manager 1 Security & Audit Agent: {e}")
            self._log_to_his(target_id="USER_OR_NEXT", job_data={"task_type": "OUTGOING_RESULT", "payload": {"status": "error", "message": str(e)}}); return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})

    def _handle_bid_request(self, task, task_id, job_desc, session_id, model_name, comm_type):
        with self._get_lm_context(model_name, session_id):
            # Step 1: Qualification
            qual_module = dspy.ChainOfThought(QualificationSignature)
            domain_interest = "Static Code Analysis, SAST, CVE Dependency Auditing, Software License Compliance, PCI-DSS/SOC2/GDPR Compliance"
            qual_res = qual_module(job_description=job_desc, domain_fields_of_interest=domain_interest)
            qual_data = extract_json(qual_res.qualification_result) or {}

            if isinstance(qual_data, dict) and not qual_data.get("is_qualified", True):
                log.info(f"Manager 1 declined job {task_id}: {qual_data.get('reasoning')}")
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

            # Step 2: Task Breakdown
            breakdown_module = dspy.ChainOfThought(TaskBreakdownSignature)
            breakdown_res = breakdown_module(job_description=job_desc, subordinates_info=json.dumps(self.subordinates))
            breakdown_data = extract_json(breakdown_res.breakdown_result) or {}
            assignments = breakdown_data.get("subtask_assignments", []) if isinstance(breakdown_data, dict) else []

        # Step 3: Consult sub-agents with event_type="assess"
        assess_responses = {}
        for sub_id in self.subordinates:
            instruction = f"Assess security sub-task for {sub_id}"
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

        # Step 4: Bid Aggregation
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
        """Ask the LLM who implements and who reviews, then sanity-check the answer.

        The plan is only honoured if it names real subordinates; anything else falls
        back to the role convention so a bad generation cannot stall the phase.
        """
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
            if not verifiers and self.subordinates:      # no natural critic in this team
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

    @staticmethod
    def _new_solution():
        return {"files": {}, "contributions": {}}

    @staticmethod
    def _merge_into(merged, sub_id, out):
        """Fold one implementer's output into the single solution the verifier sees.

        Files are keyed by path and the latest write wins, so agents owning different
        files sit side by side while a later edit to the same file replaces the older one.
        """
        for f in out.get("modified_files") or []:
            if isinstance(f, dict) and f.get("path") and isinstance(f.get("content"), str):
                merged["files"][f["path"]] = f["content"]
        merged["contributions"][sub_id] = {k: v for k, v in out.items() if k != "modified_files"}

    @staticmethod
    def _original_files(job_desc):
        """Files supplied in the brief as '=== FILE: <path> ===' sections."""
        files = {}
        for m in re.finditer(r"^=== FILE: (\S+)[^\n]*===\n(.*?)(?=^=== |\Z)", job_desc or "", re.S | re.M):
            files[m.group(1)] = m.group(2).rstrip("\n")
        return files

    @staticmethod
    def _effective_files(merged, originals):
        """What the delivery really contains: returned files laid over the originals.

        A file no implementer returned is still part of the delivery - unchanged - so its
        original defects are checked instead of silently skipped.
        """
        effective = dict(originals)
        by_name = {os.path.basename(p): p for p in originals}
        for path, content in merged["files"].items():
            effective.pop(by_name.get(os.path.basename(path), path), None)
            effective[path] = content
        return effective

    @staticmethod
    def _config_lookup(doc, dotted):
        """(found, value) for a dotted key such as 'session.cookie_secure'."""
        node = doc
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return False, None
            node = node[part]
        return True, node

    @staticmethod
    def _undefined_names(tree):
        """[(name, first_line)] for names read in the module but bound nowhere in it.

        Deliberately loose about scope - a name bound anywhere in the file counts as defined -
        so it never flags valid code; it catches the runtime NameError class such as
        `except binascii.Error` without `import binascii`. Skipped for star imports.
        """
        bound = set(dir(builtins)) | {"__file__", "__builtins__", "__path__", "__annotations__"}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and any(a.name == "*" for a in node.names):
                return []
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                bound.update((a.asname or a.name).split(".")[0] for a in node.names)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                bound.add(node.name)
            elif isinstance(node, ast.arg):
                bound.add(node.arg)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                bound.add(node.id)
            elif isinstance(node, ast.ExceptHandler) and node.name:
                bound.add(node.name)
            elif isinstance(node, (ast.Global, ast.Nonlocal)):
                bound.update(node.names)
            elif type(node).__name__ in ("MatchAs", "MatchStar") and getattr(node, "name", None):
                bound.add(node.name)
            elif type(node).__name__ == "MatchMapping" and getattr(node, "rest", None):
                bound.add(node.rest)
        missing = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Store) and node.id not in bound:
                missing[node.id] = min(missing.get(node.id, node.lineno), node.lineno)
        return sorted(missing.items(), key=lambda item: item[1])

    def _measure_solution(self, merged, criteria, job_desc=""):
        """Facts checked in code, including the job's security acceptance criteria.

        The model is never trusted to judge anything a program can check: vulnerable pins,
        required config values and forbidden literals are gated here and override any verdict.
        """
        facts = {"files_present": sorted(merged["files"]), "python_syntax": {}}
        hard = []
        if not merged["files"]:
            hard.append("No modified files were returned - return complete corrected files in modified_files.")
        for path, content in merged["files"].items():
            if not path.endswith(".py"):
                continue
            try:
                tree = ast.parse(content)
                facts["python_syntax"][path] = "ok"
            except SyntaxError as e:
                facts["python_syntax"][path] = f"SyntaxError at line {e.lineno}: {e.msg}"
                hard.append(f"{path} does not parse (SyntaxError at line {e.lineno}: {e.msg}) - return the complete, valid file.")
                continue
            undefined = self._undefined_names(tree)
            if undefined:
                facts.setdefault("undefined_names", {})[path] = [name for name, _ in undefined]
                hard.append(f"{path} uses names that are never imported or defined, so it fails at runtime: "
                            + ", ".join(f"'{name}' (line {line})" for name, line in undefined)
                            + " - add the missing imports or definitions to that file.")

        effective = self._effective_files(merged, self._original_files(job_desc))
        facts["files_unchanged"] = sorted(p for p in effective if p not in merged["files"])

        # 1. vulnerable pins that must not remain
        forbidden = {re.sub(r"\s+", "", pin).lower(): pin for pin in criteria.get("forbidden_pins") or []}
        if forbidden:
            present = []
            for path, content in effective.items():
                if not re.match(r"requirements.*\.txt$", os.path.basename(path)):
                    continue
                for line in content.splitlines():
                    norm = re.sub(r"\s+", "", line.split("#", 1)[0]).lower()
                    if norm in forbidden:
                        present.append(f"{path}: {forbidden[norm]}")
            facts["forbidden_pins_present"] = present
            if present:
                hard.append("Vulnerable dependency pins are still present and must be upgraded to safe versions: "
                            + ", ".join(present) + ".")

        # 2. required configuration values
        required_config = criteria.get("required_config") or {}
        if required_config:
            docs = {}
            for path, content in effective.items():
                if not path.endswith((".yaml", ".yml")):
                    continue
                try:
                    docs[path] = yaml.safe_load(content) or {}
                except yaml.YAMLError as e:
                    hard.append(f"{path} is not valid YAML ({str(e).splitlines()[0]}) - return the complete, valid file.")
            checks = {}
            for key, want in required_config.items():
                found = [(path, value) for path, doc in docs.items()
                         for ok, value in [self._config_lookup(doc, key)] if ok]
                if not found:
                    checks[key] = {"required": want, "actual": None}
                    hard.append(f"Config setting '{key}' is missing; it must be set to {json.dumps(want)}.")
                    continue
                path, got = found[0]
                checks[key] = {"required": want, "actual": got, "file": path}
                if got != want:
                    hard.append(f"{path}: '{key}' is {json.dumps(got)}; it must be {json.dumps(want)}.")
            facts["required_config"] = checks

        # 3. literals that must not appear anywhere in the delivery
        literals = criteria.get("forbidden_code") or []
        if literals:
            hits = [f"{path}: '{lit}'" for lit in literals for path, content in effective.items() if lit in content]
            facts["forbidden_code_present"] = hits
            if hits:
                hard.append("Forbidden literals are still present: " + ", ".join(hits) + ".")

        return facts, hard

    @staticmethod
    def _deliverable(merged):
        return {"files": merged["files"]}

    def _handle_bid_response(self, task, task_id, job_desc, session_id, model_name, comm_type):
        log.info(f"Manager 1 won bid for task {task_id}. Starting implementation phase...")
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
                    "text": f"Implement security audit sub-task for {job_desc}",
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
    main(Manager1SecurityAuditAgent)
