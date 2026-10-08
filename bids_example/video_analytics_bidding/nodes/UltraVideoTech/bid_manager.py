"""UltraVideoTech -- Bid Manager.

The only agent in this company that speaks to the outside world. It receives the
`bid_request` from OpenArcade, decides whether the work is Video Analytics at all, walks
its five subordinates in a fixed order, and submits exactly one bid.

It hears of a job by one of two routes. The `bid_request` is the primary one. A company
that listens on a topic -- `metadata.subject_metadata.topics` in its spec -- also polls
OpenArcade for jobs carrying that topic or naming it, and bids on those through the same
pipeline (`on_bidding_task`). Both routes go through `Discovery.claim`, so a job is bid
on once however it was found.

**Every terminal path submits a bid.** Qualification failure, compliance failure, a
licence ceiling, a Head Agent refusal, a subordinate that times out or returns nonsense
-- all of them end in a declining bid rather than silence. This is not politeness:
OpenArcade evaluates only once *every* participant has a bid on file, and there is no
timeout, so one silent Bid Manager stalls the entire round forever and the buyer's task
sits in "bidding" indefinitely.

This file is deliberately standalone. Its four siblings are near-identical copies, so
any company can diverge in ways `config.yaml` cannot express without disturbing the
others. Only genuinely shared *utilities* -- config loading, the RFP reader, MinIO, the
scoring helpers -- are imported from elsewhere.
"""
import json
import logging
import os
import sys
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

import dspy

from agents_sdk.core.agent_executor import AgentTask, AgentResult, Context
from agents_sdk.core.known_agents import KnownAgents
from agents_sdk.core.main import main
from agents_sdk.core.bidding_client import BiddingClient, BidJob, BidSubmission

from utils.dspy_aios_llms import AIOS_DSPy_LMs
from utils.json_utils import extract_json
from utils.va_bid_utils import normalize_va_bid

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))
from common import company_config, his_logger, orcade, rfp_reader, spec_env  # noqa: E402

log = logging.getLogger(__name__)

COMPANY = "UltraVideoTech"
ROLE = "bid_manager"

# Reserved key inside task_registry, alongside the session_id keys.
BID_JOB_INDEX = "bid_job_index"

# The chain, in order.
#
#   role   -- the subordinate's `persona.role`, which is how a discovered agent is
#             matched to its position in this workflow
#   key    -- the name its report is filed under
#   needs  -- the prior reports it receives; a stage is given what it needs to do its
#             job and nothing more, so the handoffs stay readable
STAGES = [
    ("ai_compliance", "compliance", []),
    ("sizing", "sizing", ["compliance"]),
    ("finance", "finance", ["compliance"]),
    ("bid_reviewer", "review", ["compliance", "sizing", "finance"]),
    ("head", "approval", ["compliance", "sizing", "finance", "review"]),
]

STAGE_ROLES = [role for role, _key, _needs in STAGES]


class QualificationSignature(dspy.Signature):
    """
    ### ROLE
    You are the Bid Manager for a Video Analytics company.

    ### TASK
    Decide whether the incoming project is a Video Analytics / video surveillance
    project -- CCTV analytics, face recognition, crowd analytics, ANPR, intrusion
    detection, video management systems, command-and-control centre video, or similar.

    Judge the project only on what the description says. A project that is mostly about
    something else (road construction, payroll software, a call centre) is NOT qualified,
    even if it mentions cameras in passing.

    ### OUTPUT
    Output EXACTLY a JSON block:
    {"is_qualified": bool, "reasoning": "string", "out_of_scope": "string"}
    """
    job_description = dspy.InputField(desc="Incoming project / RFP description")
    domain_fields_of_interest = dspy.InputField(desc="Video Analytics capabilities this company offers")
    qualification_result = dspy.OutputField(desc='JSON block: {"is_qualified": bool, "reasoning": "string", "out_of_scope": "string"}')


class UltraVideoTechBidManagerAgent:

    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        self.company = COMPANY
        self.config = company_config.load(self.company)
        self.slug = self.config["company"]["slug"]

        self.persona_default_system_message = getattr(
            getattr(self.subject, "persona", None), "default_system_message", ""
        )
        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        self.default_model = "aios:qwen3-1-7b-vllm-block"
        try:
            if self.subject.integrations and self.subject.integrations.models:
                self.default_model = self.subject.integrations.models[0].llm_block_id
        except Exception:
            pass

        # MinIO, the function registry and HIS all come from this subject's own spec.
        # Done before anything reads them, and before the first HIS client is built.
        spec_env.apply(subject)
        self.his_client = his_logger.build_client(subject)
        self.task_registry: Dict[str, Any] = {}

        self.subordinates = self._discover_subordinates()
        log.info("%s Bid Manager subordinates: %s", self.company, self.subordinates)

        # --- OpenArcade ---------------------------------------------------------------
        # Two threads can bid: the Redis worker (`on_data`, for a bid_request) and the
        # poller (`on_bidding_task`, for a polled job). A BiddingClient wraps one
        # requests.Session, which is not guaranteed thread-safe, so each thread has its
        # own client. Both exist before the poller starts, because it can call
        # `on_bidding_task` straight away.
        self._orcade_url = orcade.url(subject)
        self._task_client = self._new_client()      # the Redis worker thread
        self._poll_client = self._new_client()      # the poller thread
        self._local = threading.local()             # which of the two this thread uses
        # Pipelines run one at a time, whichever route started them: they share the HIS
        # client, the task registry and the model context.
        self._bid_lock = threading.Lock()
        self.discovery = orcade.Discovery(self._own_subject_id(), orcade.topics(subject),
                                          orcade.poll_seconds(subject))
        self.discovery.start(self, self._poll_client)

    # --- subordinate discovery --------------------------------------------

    def _discover_subordinates(self):
        """Find this company's own agents and place each one in the workflow.

        Every agent spec carries its company slug in `subject_search_tags`, so one
        query returns this company's agents and nobody else's -- a Bid Manager must
        never end up consulting a rival's Finance Agent. Each result is then matched to
        its position in STAGES by its `persona.role`, so the workflow is assembled from
        what the agents say they are rather than from ids assumed here.

        Returns `{role: subject_id}`. Roles that discovery does not turn up fall back
        to the conventional id, so a subject DB that is briefly unreachable degrades to
        a working round instead of an empty one -- and the gap is logged.
        """
        found = {}
        try:
            known = KnownAgents(default_compact=False)
            known.query_and_add(query={"metadata.subject_search_tags": self.slug})
            for agent in known.list_all():
                role = self._role_of(agent)
                if role == "bid_manager" or agent.id == self._own_subject_id():
                    continue                      # that is us
                if role not in STAGE_ROLES:
                    log.debug("%s: ignoring %s with role %r, not part of the bid workflow",
                              self.company, agent.id, role)
                    continue
                if role in found:
                    log.warning("%s: two agents claim role %r (%s and %s); keeping the first",
                                self.company, role, found[role], agent.id)
                    continue
                found[role] = agent.id
            log.info("%s: discovered %d subordinate(s) by tag %r", self.company, len(found), self.slug)
        except Exception as e:
            log.error("%s: subordinate discovery failed (%s); falling back to conventional ids",
                      self.company, e)

        for role in STAGE_ROLES:
            if role not in found:
                fallback = f"{self.slug}-{role.replace('_', '-')}"
                log.warning("%s: no agent discovered for role %r; falling back to %s",
                            self.company, role, fallback)
                found[role] = fallback
        return found

    def _own_subject_id(self):
        return getattr(getattr(self.subject, "identity", None), "subject_id", None) \
            or f"{self.slug}-bid-manager"

    @staticmethod
    def _role_of(agent):
        """A discovered agent's role, from its persona or its metadata."""
        subject = getattr(agent, "subject", None)
        role = getattr(getattr(subject, "persona", None), "role", None)
        if role:
            return role
        metadata = getattr(getattr(subject, "metadata", None), "subject_metadata", None) or {}
        return metadata.get("role", "")

    # --- state -------------------------------------------------------------

    def _task_entry(self, session_id, task_id):
        return self.task_registry.setdefault(session_id, {}).setdefault(task_id, {})

    def _init_task(self, session_id, task_id, rfp_url=None, job_desc=None):
        entry = self._task_entry(session_id, task_id)
        entry.setdefault("company", self.company)
        entry.setdefault("stage", "received")
        entry.setdefault("reports", {})
        if rfp_url:
            entry["rfp_url"] = rfp_url
        if job_desc:
            entry.setdefault("job_description", job_desc)
        return entry

    def _index_bid_job(self, bid_job_id, session_id, task_id):
        """Remember which session/task a bid job belongs to.

        A `bid_winner` notification carries neither the job spec nor the originating
        task_id, so without this index the winner hop would mint a fresh session and
        lose everything cached while the bid was being prepared.
        """
        if bid_job_id:
            self.task_registry.setdefault(BID_JOB_INDEX, {})[bid_job_id] = {
                "session_id": session_id, "task_id": task_id
            }

    def _lookup_bid_job(self, bid_job_id):
        record = self.task_registry.get(BID_JOB_INDEX, {}).get(bid_job_id) or {}
        return record.get("session_id"), record.get("task_id")

    # --- transport ---------------------------------------------------------

    def _get_lm_context(self, model_name, session_id):
        return dspy.settings.context(
            lm=self.aios_dspy_lm.get_choosen_model(model_name=model_name, session_id=session_id)
        )

    def _report(self, event, payload, stage=None, bid_job_id=None,
                destination_id="USER_OR_NEXT"):
        """Tell HIS what this manager received, dispatched or produced.

        Reporting must never change the outcome: a Bid Manager that failed to log and
        therefore failed to bid would stall the entire round, which is far worse than a
        gap in the dashboard.
        """
        his_logger.report(self.his_client, subject_id=self._own_subject_id(),
                          company=self.company, role=ROLE, event=event, payload=payload,
                          stage=stage, bid_job_id=bid_job_id, destination_id=destination_id)

    # OpenArcade runs the pre-qualification function as a Kubernetes job on every
    # submission. With five Bid Managers submitting at once the registry can take longer
    # than its own client allows, and the submission comes back as a read timeout. The
    # bid is simply not on file then -- and because evaluation waits for every
    # participant with no timeout, one lost submission stalls the round for good. So a
    # transport failure is retried rather than reported once and abandoned.
    SUBMIT_ATTEMPTS = 4
    SUBMIT_BACKOFF = 5.0      # seconds, doubling; ~75s of patience in total

    @staticmethod
    def _is_already_on_file(error):
        """Did OpenArcade refuse this because the company already has a bid here?

        Only the message can answer that. OpenArcade answers a pre-qualification
        rejection with 409 as well, so the status code alone does not distinguish "you
        already bid" from "you did not qualify" -- and reading a rejection as a duplicate
        makes this return success without ever putting the declining bid on file, which
        strands the round. `_is_pqt_rejection` is therefore checked first, and this stays
        message-based.

        The case it does cover: a submission whose write landed but whose response never
        came back (the registry timing out inside `POST /bid-jobs/{id}/bids`) is retried
        by the loop below, and the retry finds its own bid already stored. Without this
        the retry burns every remaining attempt and reports SUBMISSION_FAILED for a bid
        that is sitting on the job.
        """
        return "already" in str(error).lower()

    @staticmethod
    def _is_pqt_rejection(error):
        """Did pre-qualification reject this bid, as opposed to the call failing?"""
        text = str(error).lower()
        return "pqt" in text and "reject" in text

    def _new_client(self):
        """A BiddingClient for one thread, or None when no OpenArcade URL is configured."""
        if not self._orcade_url:
            log.error("%s: ORCADE_URL is set neither in the pod environment nor in the spec's "
                      "persona.config.parameters; no bid can be submitted", self.company)
            return None
        return BiddingClient(self._orcade_url, timeout=orcade.SUBMIT_TIMEOUT)

    def _client(self):
        """This thread's client: the poller's own on the poller thread, the Redis worker's otherwise."""
        client = getattr(self._local, "client", None) or self._task_client
        if client is None:
            raise RuntimeError("no OpenArcade client: ORCADE_URL is not configured")
        return client

    @staticmethod
    def _is_retryable(error):
        """Only a transport failure or a server error can be fixed by trying again.

        A 4xx is OpenArcade's answer -- the job is closed or full, the subject is not on
        the roster, the job does not exist -- and it will say the same thing next time.
        """
        status = getattr(error, "status_code", None)
        return status is None or status >= 500

    def _submit_to_openarcade(self, bid_job_id, bid_data):
        """The one call that keeps the round alive. Failing here strands the job."""
        if not bid_job_id:
            log.warning("%s: no bid_job_id on the request; cannot submit a bid", self.company)
            return False

        try:
            client = self._client()
        except Exception as e:
            log.error("%s: cannot submit the bid for %s: %s", self.company, bid_job_id, e)
            self._report("SUBMISSION_FAILED",
                         {"bid_job_id": bid_job_id, "bid_status": bid_data.get("bid_status"),
                          "attempts": 0, "error": str(e)[:500],
                          "consequence": "no bid on file; the round cannot complete"},
                         stage="submit", bid_job_id=bid_job_id, destination_id="openarcade")
            return False
        subject_id = getattr(self.subject.identity, "subject_id", None) or f"{self.slug}-bid-manager"

        last_error = None
        for attempt in range(1, self.SUBMIT_ATTEMPTS + 1):
            try:
                client.submit_bid(BidSubmission(bid_job_id=bid_job_id,
                                                bid_subject_id=subject_id,
                                                bid_data=bid_data))
                log.info("%s: submitted %s bid for %s",
                         self.company, bid_data.get("bid_status"), bid_job_id)
                return True
            except Exception as e:
                last_error = e

                # Pre-qualification rejecting this company is an expected outcome, not a
                # transport failure, and retrying would only be rejected again. But
                # OpenArcade does not keep the rejected bid, so the company would have
                # nothing on file and the round could never resolve. A declining bid
                # carrying the rejection passes pre-qualification un-judged, records why
                # the company is out, and lets the round finish.
                if self._is_pqt_rejection(e):
                    log.info("%s: pre-qualification rejected the bid -- %s", self.company, e)
                    return self._submit_pqt_rejection(client, subject_id, bid_job_id,
                                                      bid_data, e)

                if self._is_already_on_file(e):
                    log.info("%s: a bid for %s is already on file (%s); treating as submitted",
                             self.company, bid_job_id, e)
                    return True

                if not self._is_retryable(e):
                    log.error("%s: OpenArcade refused the bid for %s and trying again cannot "
                              "change that: %s", self.company, bid_job_id, e)
                    break

                if attempt < self.SUBMIT_ATTEMPTS:
                    delay = self.SUBMIT_BACKOFF * (2 ** (attempt - 1))
                    log.warning("%s: bid submission attempt %d/%d failed (%s); retrying in %.0fs",
                                self.company, attempt, self.SUBMIT_ATTEMPTS, e, delay)
                    time.sleep(delay)

        # Out of attempts. This company has no bid on file, and OpenArcade waits for
        # every participant with no timeout -- so the round is now stuck and the only
        # trace is this line in one pod's log. Report it, because a stalled round
        # otherwise looks identical to a slow one.
        log.error("%s: bid submission failed for %s after %d attempt(s): %s",
                  self.company, bid_job_id, attempt, last_error)
        self._report("SUBMISSION_FAILED",
                     {"bid_job_id": bid_job_id,
                      "bid_status": bid_data.get("bid_status"),
                      "attempts": attempt,
                      "error": str(last_error)[:500],
                      "consequence": "no bid on file; the round cannot complete"},
                     stage="submit", bid_job_id=bid_job_id, destination_id="openarcade")
        return False

    def _submit_pqt_rejection(self, client, subject_id, bid_job_id, bid_data, rejection):
        """Put the pre-qualification rejection on file as a declining bid."""
        declined = self._declining_bid(
            "pqt",
            "did not clear pre-qualification (va-bidding-pqt): certification, "
            "supplied-licence or past-project record below the RFP's bar")
        declined["bid_rejected"] = True
        declined["pqt_response"] = str(rejection)[:300]   # the raw text, for debugging
        if bid_data.get("agent_trace"):
            declined["agent_trace"] = bid_data["agent_trace"]

        self._report("PQT_REJECTED", declined, stage="declined:pqt",
                     bid_job_id=bid_job_id, destination_id="openarcade")
        try:
            client.submit_bid(BidSubmission(bid_job_id=bid_job_id,
                                            bid_subject_id=subject_id,
                                            bid_data=declined))
            log.info("%s: recorded the pre-qualification rejection as a declining bid",
                     self.company)
            return True
        except Exception as e:
            log.error("%s: could not record the pqt rejection for %s: %s",
                      self.company, bid_job_id, e)
            self._report("SUBMISSION_FAILED",
                         {"bid_job_id": bid_job_id,
                          "bid_status": "declined",
                          "error": str(e)[:500],
                          "consequence": "pqt rejection not on file; the round cannot complete"},
                         stage="submit", bid_job_id=bid_job_id, destination_id="openarcade")
            return False

    def _dispatch(self, subject_id, task, task_id, session_id, comm_type, job_data):
        """Send one stage to one subordinate over the configured transport."""
        if comm_type == "p2p":
            res = self.context.p2p_manager.send_and_wait_sync(
                task_id=task_id, subject_id=subject_id, task_data=job_data)
            return res.get("data", {})
        if comm_type == "delegate":
            return self.context.delegator.submit_and_wait(
                subject_id=subject_id, session_id=session_id, task_id=task_id, task_data=job_data)
        self.context.direct.submit(to=subject_id, session_id=session_id, task=task, job_data=job_data)
        return {"status": "dispatched"}

    @staticmethod
    def _report_of(response):
        """A subordinate's report, whatever envelope it came back in.

        The transports nest differently: a delegate reply arrives as
        `{"data": {"job_output": {...}}}` while a p2p reply is already
        `{"job_output": {...}}`. Unwrapping one layer is therefore not enough -- it
        leaves the AgentResult envelope in place, and the next stage reads
        `compliance["covered_usecases"]` off a dict that only has `job_output`,
        `is_error` and friends. It finds nothing, sizes nothing, and the company
        declines with a full and perfectly good compliance report sitting one level
        down. So strip transport wrappers until the report itself is in hand.

        `job_output` is terminal: whatever is inside it is the subordinate's own
        report, and a `data` key of its own belongs to that report, not to an envelope.
        """
        MAX_DEPTH = 5   # transports nest once or twice; this is a runaway guard
        for _ in range(MAX_DEPTH):
            if not isinstance(response, dict):
                return {}
            inner = response.get("job_output")
            if isinstance(inner, dict):
                return inner
            nested = None
            for key in ("data", "output"):
                candidate = response.get(key)
                if isinstance(candidate, dict):
                    nested = candidate
                    break
            if nested is None:
                return response
            response = nested
        return response if isinstance(response, dict) else {}

    # --- framework hooks ---------------------------------------------------

    def get_muxer(self):
        return None

    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        return [task]

    def on_data(self, task: AgentTask) -> AgentResult:
        try:
            data = task.job_data or {}
            self._report("INCOMING_TASK", data,
                         bid_job_id=data.get("bid_job_id")
                         or (data.get("bid_job") or {}).get("bid_job_id"))
            event_type = data.get("type", data.get("event_type", "bid_request"))
            task_id = data.get("task_id", task.task_id)
            session_id = data.get("session_id", str(uuid.uuid4()))
            comm_type = data.get("communication_type", "delegate")
            model_name = data.get("model_name", self.default_model)

            bid_job = data.get("bid_job") or {}
            bid_job_id = data.get("bid_job_id") or bid_job.get("bid_job_id")
            description = bid_job.get("bid_job_description") or {}
            rfp_url = description.get("rfp_url") or data.get("rfp_url")
            if description:
                job_desc = description.get("text") or json.dumps(description)
            else:
                job_desc = data.get("text", "")

            if event_type in ("bid_winner", "bid_response"):
                prior_session, prior_task = self._lookup_bid_job(bid_job_id)
                if prior_task:
                    session_id, task_id = prior_session or session_id, prior_task
                else:
                    log.warning("%s: no cached context for bid_job %s", self.company, bid_job_id)

            entry = self._init_task(session_id, task_id, rfp_url, job_desc)
            if bid_job_id:
                entry["bid_job_id"] = bid_job_id
                self._index_bid_job(bid_job_id, session_id, task_id)

            if event_type == "bid_request":
                # A polled job was claimed by `Discovery.admit` before it got here; a
                # bid_request still has to claim, and loses if the poller already did.
                if data.get("source") != "poll" and not self.discovery.claim(bid_job_id):
                    log.info("%s: bid job %s is already being handled by the other route",
                             self.company, bid_job_id)
                    return AgentResult(task_id=task_id, job_output={
                        "status": "duplicate", "bid_job_id": bid_job_id})
                with self._bid_lock:
                    return self._handle_bid_request(task, task_id, session_id, comm_type,
                                                    model_name)
            if event_type in ("bid_winner", "bid_response"):
                return self._handle_bid_winner(task, task_id, session_id, data)

            log.warning("%s: unhandled event_type %r", self.company, event_type)
            return AgentResult(task_id=task.task_id, skip=True)

        except Exception as e:
            # Even a failure this far out must leave a bid behind, or the round stalls.
            log.exception("%s Bid Manager failed: %s", self.company, e)
            try:
                bid_job_id = (task.job_data or {}).get("bid_job_id") or \
                             ((task.job_data or {}).get("bid_job") or {}).get("bid_job_id")
                bid = self._declining_bid("error", f"bid manager error: {e}")
                self._submit_to_openarcade(bid_job_id, bid)
                return AgentResult(task_id=task.task_id, job_output=bid)
            except Exception:
                return AgentResult(task_id=task.task_id, is_error=True, error_data={"message": str(e)})

    # --- polled jobs -------------------------------------------------------

    def on_bidding_task(self, bid_task_data: BidJob) -> None:
        """A job found by polling for this company's topics. Runs on the poller thread.

        Whether to bid is `Discovery.admit`'s decision: an open job is applied to, a
        roster job (closed or mixed) is taken over only if its bid_request never came,
        and a job this company is not on the roster of is left alone. What follows is the
        same pipeline a bid_request runs -- the polled job is dressed as one and handed to
        `on_data`, so qualification, the five stages, HIS reporting and the
        decline-on-any-failure rule are not written twice.
        """
        self._local.client = self._poll_client      # this thread's own client
        job = bid_task_data
        why_not = self.discovery.admit(job)
        if why_not:
            log.info("%s: not bidding on polled job %s -- %s", self.company, job.bid_job_id, why_not)
            return
        log.info("%s: bidding on polled %s-mode job %s", self.company, job.bid_job_mode, job.bid_job_id)
        self.on_data(AgentTask(task_id=str(uuid.uuid4()), job_data={
            "type": "bid_request",
            "source": "poll",
            "bid_job": job.to_dict(),
            "bid_job_id": job.bid_job_id,
        }))

    # --- bid request -------------------------------------------------------

    def _handle_bid_request(self, task, task_id, session_id, comm_type, model_name):
        entry = self._task_entry(session_id, task_id)
        bid_job_id = entry.get("bid_job_id")
        rfp_url = entry.get("rfp_url")
        job_desc = entry.get("job_description") or ""

        # The RFP text is the honest basis for qualification. If it cannot be fetched,
        # fall back to the job description rather than declining on a transport problem.
        if rfp_url:
            try:
                job_desc = rfp_reader.excerpt(rfp_url, max_chars=40000)
            except Exception as e:
                log.warning("%s: could not read the RFP at %s (%s); qualifying on the job "
                            "description instead", self.company, rfp_url, e)

        # Step 1 -- is this Video Analytics at all?
        capabilities = ", ".join(uc["name"] for uc in self.config["usecases"])
        try:
            with self._get_lm_context(model_name, session_id):
                qual = dspy.ChainOfThought(QualificationSignature)(
                    job_description=job_desc[:40000],
                    domain_fields_of_interest=capabilities,
                )
            verdict = extract_json(qual.qualification_result) or {}
        except Exception as e:
            log.warning("%s: qualification failed (%s); treating as unqualified", self.company, e)
            verdict = {"is_qualified": False, "reasoning": f"qualification error: {e}"}

        entry["qualification"] = verdict
        if not verdict.get("is_qualified"):
            reason = verdict.get("reasoning") or "not a Video Analytics project"
            return self._decline(task, task_id, session_id, bid_job_id, "qualification", reason)

        entry["stage"] = "qualified"

        # Step 2 -- walk the subordinates in order.
        reports = entry.setdefault("reports", {})
        for role, key, needs in STAGES:
            subject_id = self.subordinates.get(role)
            if not subject_id:
                return self._decline(task, task_id, session_id, bid_job_id, "error",
                                     f"no subordinate available for the {key} stage")
            payload = {
                "type": "va_bid_stage",
                "stage": key,
                "company": self.company,
                "rfp_url": rfp_url,
                "bid_job_id": bid_job_id,
                "session_id": session_id,
                "task_id": task_id,
                "upstream": {k: reports.get(k, {}) for k in needs},
            }
            started = time.time()
            self._report("STAGE_DISPATCH", payload, stage=key, bid_job_id=bid_job_id,
                         destination_id=subject_id)
            try:
                report = self._report_of(
                    self._dispatch(subject_id, task, task_id, session_id, comm_type, payload)
                )
            except Exception as e:
                log.exception("%s: %s stage failed", self.company, key)
                self._trace(entry, key, subject_id, payload, {"error": str(e)},
                            time.time() - started)
                return self._decline(task, task_id, session_id, bid_job_id, "error",
                                     f"{key} stage failed: {e}")

            reports[key] = report
            entry["stage"] = key
            self._trace(entry, key, subject_id, payload, report, time.time() - started)
            self._report("STAGE_RESULT", report, stage=key, bid_job_id=bid_job_id,
                         destination_id=subject_id)
            log.info("%s: %s stage complete", self.company, key)

            # A stage may end the chain: compliance can find the catalogue does not
            # cover the work, or that the licence count is outside what we supply.
            if report.get("decline_reason"):
                stage_name = report.get("decline_stage") or key
                return self._decline(task, task_id, session_id, bid_job_id,
                                     stage_name, report["decline_reason"])

        # Step 3 -- the Head Agent is the sole authority for proceeding.
        approval = reports.get("approval") or {}
        if not approval.get("approved"):
            return self._decline(task, task_id, session_id, bid_job_id, "approval",
                                 approval.get("reason") or "not approved by the Head Agent")

        bid_data = self._assemble_bid(reports)
        bid_data["agent_trace"] = entry.get("agent_trace", [])
        entry["bid_data"] = bid_data
        entry["stage"] = "bid_submitted"

        self._report("OUTGOING_RESULT", bid_data, stage="bid_submitted",
                     bid_job_id=bid_job_id, destination_id="openarcade")
        self._submit_to_openarcade(bid_job_id, bid_data)
        return AgentResult(task_id=task_id, job_output=bid_data)

    # --- bid assembly ------------------------------------------------------

    def _assemble_bid(self, reports):
        """The priced bid, per contracts/bid-payload.md.

        Numbers are settled here rather than left to however a model worded them: the
        evaluator reads `total_budget` and the four `sizing` values as numbers, and a
        bid saying "4.85 Cr" is unscoreable.
        """
        compliance = reports.get("compliance") or {}
        sizing = reports.get("sizing") or {}
        finance = reports.get("finance") or {}
        review = reports.get("review") or {}
        approval = reports.get("approval") or {}

        bid = {
            "bid_status": "submitted",
            "company": self.company,

            "total_budget": finance.get("total_budget"),
            "currency": self.config["pricing"].get("currency", "INR"),
            "commercials_url": finance.get("document_url"),
            "one_time_cost": finance.get("one_time_cost"),
            "amc_cost": finance.get("amc_cost"),
            "proposed_timeline_weeks": finance.get("timeline_weeks"),

            "sizing": sizing.get("totals") or {},
            "sizing_url": sizing.get("document_url"),

            "compliance": {"met": compliance.get("met"), "total": compliance.get("total")},
            "compliance_points": compliance.get("points") or [],
            "live_endpoints": compliance.get("live_endpoints") or [],

            "credentials": self._credentials(),
            "review": {"ready_to_bid": review.get("ready_to_bid"),
                       "covered": review.get("covered") or [],
                       "missing": review.get("missing") or []},
            "approval": {"approved": approval.get("approved"), "reason": approval.get("reason")},
        }
        return normalize_va_bid(bid)

    # Fields whose full value is too large to carry on a bid. The dashboard shows a
    # summary; the agent's own logs have the rest.
    _TRACE_TRUNCATE = {"points": 8, "compliance_points": 8, "per_usecase": 8,
                       "line_items": 8, "usecases_required": 12, "covered": 12,
                       "missing": 12, "past_projects": 4}
    _TRACE_MAX_CHARS = 1200

    def _trace(self, entry, stage, subject_id, payload, report, seconds):
        """Record one handoff so the round can be read back afterwards.

        The trace rides on the bid rather than going to a separate store, so a single
        GET against the bidding system reproduces the whole chain -- which is what the
        dashboard reads, and what makes a finished round explainable without pod logs.
        The evaluator reads named fields only, so this cannot affect scoring.
        """
        trace = entry.setdefault("agent_trace", [])
        trace.append({
            "stage": stage,
            "subject_id": subject_id,
            "seconds": round(seconds, 2),
            "input": {
                "rfp_url": payload.get("rfp_url"),
                "upstream_reports": sorted((payload.get("upstream") or {}).keys()),
                "upstream_summary": self._summarise(payload.get("upstream") or {}),
            },
            "output": self._summarise(report),
        })

    @classmethod
    def _summarise(cls, value, depth=0):
        """A serializable, bounded view of an agent report."""
        if depth > 3:
            return "..."
        if isinstance(value, dict):
            out = {}
            for key, inner in value.items():
                if isinstance(inner, list) and key in cls._TRACE_TRUNCATE:
                    limit = cls._TRACE_TRUNCATE[key]
                    kept = [cls._summarise(v, depth + 1) for v in inner[:limit]]
                    if len(inner) > limit:
                        kept.append(f"... {len(inner) - limit} more")
                    out[key] = kept
                else:
                    out[key] = cls._summarise(inner, depth + 1)
            return out
        if isinstance(value, list):
            return [cls._summarise(v, depth + 1) for v in value[:12]]
        if isinstance(value, str) and len(value) > cls._TRACE_MAX_CHARS:
            return value[:cls._TRACE_MAX_CHARS] + f" ... [{len(value)} chars]"
        if isinstance(value, (int, float, bool)) or value is None:
            return value
        return str(value)[:cls._TRACE_MAX_CHARS]

    def _credentials(self):
        """Travels on every bid, priced or declining.

        Pre-qualification runs on each incoming bid including declines, and a missing
        credentials block would read as a credential failure rather than a decline.
        """
        credentials = self.config["credentials"]
        return {
            "certifications": list(credentials.get("certifications") or []),
            "projects_served": credentials.get("projects_served"),
            "licenses_supplied": credentials.get("licenses_supplied"),
        }

    def _declining_bid(self, stage, reason):
        return {
            "bid_status": "declined",
            "company": self.company,
            "decline_stage": stage,
            "decline_reason": str(reason)[:600],
            "credentials": self._credentials(),
        }

    def _decline(self, task, task_id, session_id, bid_job_id, stage, reason):
        log.info("%s: declining at %s -- %s", self.company, stage, reason)
        bid = self._declining_bid(stage, reason)
        bid["agent_trace"] = self._task_entry(session_id, task_id).get("agent_trace", [])
        self._task_entry(session_id, task_id).update({"stage": "declining", "bid_data": bid})
        self._report("OUTGOING_RESULT", bid, stage=f"declined:{stage}",
                     bid_job_id=bid_job_id, destination_id="openarcade")
        self._submit_to_openarcade(bid_job_id, bid)
        return AgentResult(task_id=task_id, job_output=bid)

    # --- bid winner --------------------------------------------------------

    def _handle_bid_winner(self, task, task_id, session_id, data):
        """Accept the win and echo the evaluator's reasoning back to the buyer.

        OpenArcade exposes the evaluator's `result_data` through no endpoint -- it only
        reaches the winning subject, in this notification. Echoing the score table here
        is therefore the only path by which it becomes the Xchange task's `task_output`
        and the buyer ever sees why they won.
        """
        entry = self._task_entry(session_id, task_id)
        entry["stage"] = "won"

        result_data = data.get("result_data") or data.get("task_result") or {}
        scores = result_data.get("scores") if isinstance(result_data, dict) else None

        output = {
            "acknowledged": True,
            "company": self.company,
            "bid_job_id": entry.get("bid_job_id") or data.get("bid_job_id"),
            "scores": scores or {},
            "excluded": (result_data or {}).get("excluded", []),
            "total_budget": (entry.get("bid_data") or {}).get("total_budget"),
            "commercials_url": (entry.get("bid_data") or {}).get("commercials_url"),
            "sizing_url": (entry.get("bid_data") or {}).get("sizing_url"),
            "message": f"{self.company} accepts the award and will begin mobilisation.",
            "accepted_at": time.time(),
        }
        log.info("%s: won bid job %s", self.company, output["bid_job_id"])
        self._report("OUTGOING_RESULT", output, stage="bid_winner",
                     bid_job_id=output.get("bid_job_id"))
        return AgentResult(task_id=task_id, job_output=output)


if __name__ == "__main__":
    main(UltraVideoTechBidManagerAgent)
