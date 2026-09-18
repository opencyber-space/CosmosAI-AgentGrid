import logging
import time
from agents_sdk.core.his import HisClient
import uuid
import json
import dspy
from typing import Any, Dict, List, Optional

from agents_sdk.core.agent_executor import AgentTask, AgentResult, Context
from agents_sdk.core.main import main
from agents_sdk.core.known_agents import KnownAgents
import os
from openarcade_bidding_pysdk.client import OpenarcadeClient
from utils.dspy_aios_llms import AIOS_DSPy_LMs
from utils.json_utils import extract_json
from utils.security_checks import measure_solution

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
    You are Manager 5 for Security & Audit.

    ### TASK
    Write the single sub-task instruction for the one subordinate agent, which performs the whole
    audit alone: source remediation, dependency upgrades and security configuration.

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
    You are Manager 5 for Security & Audit.

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



class ExecutionAggregationSignature(dspy.Signature):
    """
    ### ROLE
    You are Manager 5 for Security & Audit.

    ### TASK
    Synthesize the sole sub-agent's delivery into a final Security Audit Report. That sub-agent
    implemented and reviewed its own work in a single call, so `verification` carries its
    self-review verdict together with the facts this manager measured in code from the files
    it returned.

    ### OUTPUT
    Take every fact (files, pins, config values, undefined names) from verification.measured_facts -
    never estimate or restate a target as if it were achieved. Report the final verdict honestly,
    naming any check that failed.

    Output EXACTLY a JSON block: {"audit_summary": "string", "vulnerabilities_found": ["string"], "compliance_status": "string", "overall_status": "completed"}
    """
    job_description = dspy.InputField(desc="Security audit job description")
    subagent_results = dspy.InputField(desc="Execution result from the security sub-agent")
    verification = dspy.InputField(desc="Self-review verdict, measured facts and any remaining gaps")
    final_report = dspy.OutputField(desc="JSON block of final audit delivery")

# --- 2. Manager Agent Node ---

class Manager5SecurityAuditAgent:
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

        # Discover the solo security sub-agent
        try:
            known_agents = KnownAgents(default_compact=False)
            known_agents.query_and_add(query={
                "metadata.subject_search_tags": "security-solo-subordinates"
            })
            self.subordinates = [agent.id for agent in known_agents.list_all()]
            log.info("Manager 5 discovered its solo security subordinate: %s", self.subordinates)
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
        log.info(f"Preprocessing task {task.task_id} in Manager5SecurityAudit")
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
            log.exception(f"Error in Manager 5 Security & Audit Agent: {e}")
            self._log_to_his(target_id="USER_OR_NEXT", job_data={"task_type": "OUTGOING_RESULT", "payload": {"status": "error", "message": str(e)}}); return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})

    def _handle_bid_request(self, task, task_id, job_desc, session_id, model_name, comm_type):
        with self._get_lm_context(model_name, session_id):
            # Step 1: Qualification
            qual_module = dspy.ChainOfThought(QualificationSignature)
            domain_interest = "Static Code Analysis, SAST, CVE Dependency Auditing, Software License Compliance, PCI-DSS/SOC2/GDPR Compliance"
            qual_res = qual_module(job_description=job_desc, domain_fields_of_interest=domain_interest)
            qual_data = extract_json(qual_res.qualification_result) or {}

            if isinstance(qual_data, dict) and not qual_data.get("is_qualified", True):
                log.info(f"Manager 5 declined job {task_id}: {qual_data.get('reasoning')}")
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

        # Step 3: Consult the sub-agent with event_type="assess"
        assess_responses = {}
        subtask_instructions = {}
        for sub_id in self.subordinates:
            instruction = f"Assess security sub-task for {sub_id}"
            for assign in assignments:
                if assign.get("agent_id") == sub_id:
                    instruction = assign.get("instruction", instruction)
                    subtask_instructions[sub_id] = instruction

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
        # The bid_winner hop carries no breakdown, so keep the instruction for the implement call.
        self._task_entry(session_id, task_id)["subtask_instructions"] = subtask_instructions

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


    def _dispatch(self, sub_id, task, task_id, session_id, comm_type, sub_job_data):
        """Send one task to a sub-agent over the configured transport."""
        if comm_type == "p2p":
            res = self.context.p2p_manager.send_and_wait_sync(task_id=task_id, subject_id=sub_id, task_data=sub_job_data)
            return res.get("data", {})
        if comm_type == "delegate":
            return self.context.delegator.submit_and_wait(subject_id=sub_id, session_id=session_id, task_id=task_id, task_data=sub_job_data)
        self.context.direct.submit(to=sub_id, session_id=session_id, task=task, job_data=sub_job_data)
        return {"status": "dispatched"}


    @staticmethod
    def _job_output(res):
        """Strip the transport envelope and return the agent's own job_output."""
        if isinstance(res, dict) and isinstance(res.get("job_output"), dict):
            return res["job_output"]
        return res if isinstance(res, dict) else {}











    def _handle_bid_response(self, task, task_id, job_desc, session_id, model_name, comm_type):
        """One dispatch to the solo sub-agent, which implements and reviews in that same call."""
        log.info(f"Manager 5 won bid for task {task_id}. Dispatching the whole audit to its solo sub-agent...")
        entry = self._task_entry(session_id, task_id)
        criteria = (entry.get("bid_job_description") or {}).get("acceptance_criteria") or {}
        instructions = entry.get("subtask_instructions") or {}
        if not self.subordinates:
            message = "no security-solo subordinate was discovered"
            log.error(f"Manager 5 cannot implement task {task_id}: {message}")
            self._log_to_his(target_id="USER_OR_NEXT", job_data={"task_type": "OUTGOING_RESULT", "payload": {"status": "error", "message": message}})
            return AgentResult(task_id=task_id, is_error=True, error_data={"message": message})

        sub_id = self.subordinates[0]
        out = self._job_output(self._dispatch(sub_id, task, task_id, session_id, comm_type, {
            "event_type": "implement",
            "text": instructions.get(sub_id) or f"Implement the full security audit for {job_desc}",
            "job_description": job_desc,
            "acceptance_criteria": criteria,
            "session_id": session_id,
            "model_name": model_name,
            "communication_type": comm_type,
            "task_id": task_id,
        }))

        files = {f["path"]: f["content"] for f in (out.get("modified_files") or [])
                 if isinstance(f, dict) and f.get("path") and isinstance(f.get("content"), str)}
        # The sub-agent gates its own work with these same checks; re-measuring here means the
        # report never depends on the sub-agent's word for what a program can verify.
        facts, hard_failures = measure_solution(files, criteria, job_desc)
        passed = str(out.get("verdict", "fail")).lower() == "pass" and not hard_failures
        verification = {
            "verdict": "pass" if passed else "fail",
            "subagent_verdict": out.get("verdict"),
            "approval_loops": out.get("approval_loops"),
            "measured_facts": facts,
            "hard_failures": hard_failures,
            "required_changes": out.get("required_changes") or [],
            "remaining_gaps": out.get("remaining_gaps") or [],
        }
        if hard_failures:
            log.info(f"Manager 5 measured {len(hard_failures)} hard failure(s) in the delivery: {hard_failures}")

        with self._get_lm_context(model_name, session_id):
            final_res = dspy.ChainOfThought(ExecutionAggregationSignature)(
                job_description=job_desc,
                subagent_results=json.dumps({"files": files, "contributions": out.get("contributions") or {}}),
                verification=json.dumps(verification),
            )
            final_report = extract_json(final_res.final_report) or {}
        if not isinstance(final_report, dict):
            final_report = {}

        final_report["approval_loops"] = out.get("approval_loops")
        final_report["verification_verdict"] = verification["verdict"]
        final_report["measured_facts"] = facts
        final_report["hard_failures"] = hard_failures
        final_report["advisories"] = out.get("advisories") or []
        final_report["deliverable"] = {"files": files}

        entry["implement_responses"] = {sub_id: out}
        entry["final_report"] = final_report
        self._log_to_his(target_id="USER_OR_NEXT", job_data={"task_type": "OUTGOING_RESULT", "payload": final_report}); return AgentResult(task_id=task_id, job_output=final_report)


if __name__ == "__main__":
    main(Manager5SecurityAuditAgent)
