"""MultiFaceTech -- Bid Reviewer Agent.

The last check before the bid reaches the Head Agent. It reads the RFP and the three
reports assembled so far, and answers one question: has everything the buyer asked for
actually been produced?

**It reviews coverage, not correctness.** Whether the price is right or the sizing is
accurate is not its business -- those are the Finance and Sizing agents' figures to
stand behind. This agent catches the different failure: an artifact the RFP demanded
that nobody produced, a document that was meant to be attached and is not, a use case
priced but never sized.

**It reports; it does not veto.** `ready_to_bid: false` is an input to the Head Agent's
decision, not a terminal state. A reviewer that could kill a bid on its own would make
the Head Agent's approval meaningless, and the RFP's own requirements are not all
equally fatal -- the Head Agent is the one placed to weigh that.

The structural checks run in code, because "is there a commercials URL" does not need a
language model and must not depend on one. The model is used for what it is good at:
reading the RFP's stated deliverables and saying which of them the assembled bid does
not answer.
"""
import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional

import dspy

from agents_sdk.core.agent_executor import AgentTask, AgentResult, Context
from agents_sdk.core.main import main

from utils.dspy_aios_llms import AIOS_DSPy_LMs
from utils.json_utils import extract_json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))
from common import company_config, his_logger, rfp_reader, spec_env  # noqa: E402

log = logging.getLogger(__name__)

COMPANY = "MultiFaceTech"
ROLE = "bid_reviewer"


class DeliverableReviewSignature(dspy.Signature):
    """
    ### ROLE
    You are the Bid Reviewer for a Video Analytics company, checking a bid before it
    goes to the approver.

    ### TASK
    The RFP states what a bidder must submit -- documents, formats, declarations,
    evidence. Compare that against the summary of what this bid actually contains.

    Report which stated deliverables the bid ADDRESSES and which it DOES NOT. Judge only
    presence and coverage. Do not judge whether a price is competitive or a hardware
    figure is accurate; those belong to other agents and are out of your scope.

    Do not invent deliverables the RFP does not ask for. If the RFP is vague about
    submission requirements, say so rather than manufacturing a checklist.

    ### OUTPUT
    Output EXACTLY a JSON block:
    {"covered": ["string"], "missing": ["string"], "notes": "string"}
    """
    rfp_text = dspy.InputField(desc="Text extracted from the RFP document")
    bid_summary = dspy.InputField(desc="What the assembled bid contains")
    review_result = dspy.OutputField(desc='JSON block: {"covered": [...], "missing": [...], "notes": "string"}')


class MultiFaceTechBidReviewerAgent:

    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        self.company = COMPANY
        self.config = company_config.load(self.company)
        self.slug = self.config["company"]["slug"]
        self.subject_id = getattr(getattr(subject, "identity", None), "subject_id", None) \
            or f"{self.slug}-{ROLE.replace('_', '-')}"
        # MinIO, the function registry and HIS all come from this subject's own spec.
        # Done before anything reads them, and before the first HIS client is built.
        spec_env.apply(subject)
        self.his_client = his_logger.build_client(subject)

        self.aios_dspy_lm = AIOS_DSPy_LMs(subject=self.subject)
        self.default_model = "aios:qwen3-1-7b-vllm-block"
        try:
            if self.subject.integrations and self.subject.integrations.models:
                self.default_model = self.subject.integrations.models[0].llm_block_id
        except Exception:
            pass

    def _get_lm_context(self, model_name, session_id):
        return dspy.settings.context(
            lm=self.aios_dspy_lm.get_choosen_model(model_name=model_name, session_id=session_id)
        )

    def _report(self, event, payload, stage=None, bid_job_id=None,
                destination_id="USER_OR_NEXT"):
        """Tell HIS what this agent received or produced. Never affects the outcome."""
        his_logger.report(self.his_client, subject_id=self.subject_id, company=self.company,
                          role=ROLE, event=event, payload=payload, stage=stage,
                          bid_job_id=bid_job_id, destination_id=destination_id)

    def get_muxer(self):
        return None

    def on_preprocess(self, task: AgentTask) -> Optional[List[AgentTask]]:
        return [task]

    def on_data(self, task: AgentTask) -> AgentResult:
        data = task.job_data or {}
        self._report("INCOMING_TASK", data, stage=data.get("stage"),
                     bid_job_id=data.get("bid_job_id"))
        upstream = data.get("upstream") or {}
        session_id = data.get("session_id", task.task_id)
        model_name = data.get("model_name", self.default_model)

        try:
            report = self._review(upstream, data.get("rfp_url"), session_id, model_name)
        except Exception as e:
            # A reviewer that cannot review must not silently pass the bid. Reporting
            # not-ready leaves the decision where it belongs, with the Head Agent.
            log.exception("%s: review failed", self.company)
            report = {
                "company": self.company, "ready_to_bid": False,
                "covered": [], "missing": [f"review could not be completed: {e}"],
                "structural_gaps": [], "notes": str(e),
            }

        self._report("OUTGOING_RESULT", report, stage=data.get("stage"),
                     bid_job_id=data.get("bid_job_id"),
                     destination_id=f"{self.slug}-bid-manager")
        return AgentResult(task_id=task.task_id, job_output=report)

    # --- review ------------------------------------------------------------

    def _review(self, upstream, rfp_url, session_id, model_name):
        compliance = upstream.get("compliance") or {}
        sizing = upstream.get("sizing") or {}
        finance = upstream.get("finance") or {}

        structural_gaps = self._structural_gaps(compliance, sizing, finance)
        covered, missing, notes = self._deliverable_gaps(
            compliance, sizing, finance, rfp_url, session_id, model_name)

        ready = not structural_gaps
        log.info("%s: review -> ready=%s, %d structural gap(s), %d stated deliverable(s) unmet",
                 self.company, ready, len(structural_gaps), len(missing))

        return {
            "company": self.company,
            "ready_to_bid": ready,
            "covered": covered,
            "missing": structural_gaps + missing,
            "structural_gaps": structural_gaps,
            "notes": notes,
        }

    def _structural_gaps(self, compliance, sizing, finance):
        """Artifacts the bid cannot be submitted without, checked in code.

        These are the ones that make a bid unscoreable rather than merely weak: the
        evaluator reads the budget, the four hardware totals and the compliance
        fraction, and a bid missing any of them cannot be ranked at all.
        """
        gaps = []

        if finance.get("total_budget") in (None, 0):
            gaps.append("no total budget figure on the bid")
        if not finance.get("document_url"):
            gaps.append("commercial document was not produced or uploaded")

        totals = sizing.get("totals") or {}
        missing_hardware = [f for f in ("cpu_cores", "ram_gb", "disk_gb", "gpu_count")
                            if not isinstance(totals.get(f), (int, float))]
        if missing_hardware:
            gaps.append(f"sizing totals missing or non-numeric: {', '.join(missing_hardware)}")
        if not sizing.get("document_url"):
            gaps.append("sizing document was not produced or uploaded")

        if not compliance.get("total"):
            gaps.append("no compliance score -- the bid cannot be scored on use-case coverage")
        if not compliance.get("live_endpoints"):
            # Not fatal: the RFP's live benchmark simply scores zero. The Head Agent
            # decides whether bidding without it is worth doing.
            gaps_note = "no live use-case endpoints were registered"
            log.warning("%s: %s", self.company, gaps_note)

        uncovered = compliance.get("uncovered_usecases") or []
        if uncovered:
            log.info("%s: %d RFP use case(s) outside the catalogue: %s",
                     self.company, len(uncovered), uncovered)

        return gaps

    def _deliverable_gaps(self, compliance, sizing, finance, rfp_url, session_id, model_name):
        """What the RFP asked to be submitted, against what this bid contains."""
        if not rfp_url:
            return [], [], "no RFP available; only structural checks were run"

        try:
            rfp_text = rfp_reader.excerpt(rfp_url, max_chars=60000)
        except Exception as e:
            log.warning("%s: could not read the RFP for review (%s)", self.company, e)
            return [], [], f"RFP unreadable during review: {e}"

        summary = {
            "compliance_score": f"{compliance.get('met')}/{compliance.get('total')}",
            "usecases_covered": compliance.get("covered_usecases") or [],
            "usecases_not_covered": compliance.get("uncovered_usecases") or [],
            "live_endpoints": [e.get("usecase") for e in (compliance.get("live_endpoints") or [])],
            "sizing_totals": sizing.get("totals") or {},
            "sizing_document": bool(sizing.get("document_url")),
            "total_budget": finance.get("total_budget"),
            "one_time_cost": finance.get("one_time_cost"),
            "amc_cost": finance.get("amc_cost"),
            "commercial_document": bool(finance.get("document_url")),
            "timeline_weeks": finance.get("timeline_weeks"),
            "certifications_held": (self.config["credentials"].get("certifications") or []),
            "past_projects": len(self.config["credentials"].get("past_projects") or []),
        }

        try:
            with self._get_lm_context(model_name, session_id):
                result = dspy.ChainOfThought(DeliverableReviewSignature)(
                    rfp_text=rfp_text, bid_summary=json.dumps(summary, indent=2))
            parsed = extract_json(result.review_result) or {}
        except Exception as e:
            log.warning("%s: deliverable review failed (%s); structural checks stand",
                        self.company, e)
            return [], [], f"deliverable review unavailable: {e}"

        if not isinstance(parsed, dict):
            return [], [], "deliverable review returned an unusable response"

        covered = [str(x) for x in (parsed.get("covered") or [])]
        missing = [str(x) for x in (parsed.get("missing") or [])]
        return covered, missing, str(parsed.get("notes") or "")


if __name__ == "__main__":
    main(MultiFaceTechBidReviewerAgent)
