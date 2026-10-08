"""MultiFaceTech -- Head Agent.

The final authority. Nothing this company submits as a priced bid gets past here without
approval, and a refusal sends the Bid Manager down the declining path.

It weighs four things, from `config.yaml` and the reports beneath it:

  a. **Commercial viability** -- does the bid clear this company's margin floor once
     its own delivery cost is taken off?
  b. **Certification evidence** -- does the company hold what the RFP requires?
  c. **Track record** -- are there past projects to point at?
  d. **The reviewer's gaps** -- what did the Bid Reviewer say is missing?

The decision is made in code, on thresholds this company set for itself. The model is
used only to write the rationale a human would read, because an approval that a language
model could talk itself into either way is not an approval. If the model is unavailable
the decision still stands; only the wording is lost.

### On the margin figure

Each company declares `approval.cost_ratio` -- what delivering the work costs it, as a
fraction of the bare licence subtotal. Margin is then the real thing:

    margin_pct = (total_budget - licence_subtotal * cost_ratio) / total_budget * 100

and the bid is refused below `approval.min_margin_pct`. A company can be the cheapest
bid in the round and still refuse to submit it, which is what makes this a decision
rather than a formality: NewGenTech prices aggressively against a high cost base and
clears only because its own floor is low.
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
from common import company_config, his_logger, spec_env  # noqa: E402

log = logging.getLogger(__name__)

COMPANY = "MultiFaceTech"
ROLE = "head"


class ApprovalRationaleSignature(dspy.Signature):
    """
    ### ROLE
    You are the Head of Bids for a Video Analytics company, recording why a bid was
    approved or refused.

    ### TASK
    The decision has already been made on the stated criteria. Write the rationale a
    colleague would read: what carried the decision, and what the residual risk is.

    Do not re-open the decision. Do not contradict the verdict you are given. Be brief
    and concrete -- two or three sentences.

    ### OUTPUT
    Output EXACTLY a JSON block: {"rationale": "string", "risks": ["string"]}
    """
    verdict = dspy.InputField(desc="approved or refused, and the criteria results")
    bid_summary = dspy.InputField(desc="Budget, sizing, compliance and review findings")
    rationale_result = dspy.OutputField(desc='JSON block: {"rationale": "string", "risks": ["string"]}')


class MultiFaceTechHeadAgent:

    def __init__(self, subject, context: Context) -> None:
        self.subject = subject
        self.context = context
        self.company = COMPANY
        self.config = company_config.load(self.company)
        self.slug = self.config["company"]["slug"]
        self.subject_id = getattr(getattr(subject, "identity", None), "subject_id", None) \
            or f"{self.slug}-{ROLE}"
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
            decision = self._decide(upstream, session_id, model_name)
        except Exception as e:
            # An approver that cannot evaluate must not approve. The Bid Manager turns
            # this into a declining bid, which keeps the round moving.
            log.exception("%s: approval failed", self.company)
            decision = {"company": self.company, "approved": False,
                        "reason": f"approval could not be completed: {e}", "criteria": {}}

        self._report("OUTGOING_RESULT", decision, stage=data.get("stage"),
                     bid_job_id=data.get("bid_job_id"),
                     destination_id=f"{self.slug}-bid-manager")
        return AgentResult(task_id=task.task_id, job_output=decision)

    # --- decision ----------------------------------------------------------

    def _decide(self, upstream, session_id, model_name):
        compliance = upstream.get("compliance") or {}
        sizing = upstream.get("sizing") or {}
        finance = upstream.get("finance") or {}
        review = upstream.get("review") or {}

        approval = self.config["approval"]
        credentials = self.config["credentials"]

        criteria, failures = {}, []

        # (a) commercial viability -- real margin against this company's own cost base
        budget = finance.get("total_budget")
        floor = float(approval.get("min_margin_pct", 0.0))
        cost_ratio = float(approval.get("cost_ratio", 0.0))

        if not budget:
            criteria["budget"] = {"pass": False}
            criteria["margin"] = {"pass": False, "required_pct": floor,
                                  "reason": "no priced bid"}
            failures.append("no priced bid to approve")
        else:
            criteria["budget"] = {"total_budget": budget, "pass": True}
            # Cost is carried by the licence subtotal; implementation and AMC are the
            # uplift the company charges on top of it.
            subtotal = float(finance.get("licence_subtotal") or budget)
            delivery_cost = subtotal * cost_ratio
            margin_pct = (float(budget) - delivery_cost) / float(budget) * 100.0
            criteria["margin"] = {
                "margin_pct": round(margin_pct, 1),
                "required_pct": floor,
                "cost_ratio": cost_ratio,
                "delivery_cost": round(delivery_cost, 2),
                "pass": margin_pct >= floor,
            }
            if not criteria["margin"]["pass"]:
                failures.append(
                    f"margin of {margin_pct:.1f}% is below this company's floor of {floor:.1f}% "
                    f"(delivery cost {delivery_cost:,.0f} against a bid of {float(budget):,.0f})")

        # (b) certification evidence
        certifications = list(credentials.get("certifications") or [])
        needs_certs = bool(approval.get("require_certification_evidence"))
        criteria["certifications"] = {"held": certifications, "required": needs_certs,
                                      "pass": bool(certifications) or not needs_certs}
        if not criteria["certifications"]["pass"]:
            failures.append("the company holds no certification and this company requires evidence of one")

        # (c) track record
        past_projects = credentials.get("past_projects") or []
        needs_projects = bool(approval.get("require_past_projects"))
        criteria["past_projects"] = {"count": len(past_projects), "required": needs_projects,
                                     "pass": bool(past_projects) or not needs_projects}
        if not criteria["past_projects"]["pass"]:
            failures.append("no past projects to evidence delivery")

        # (d) the reviewer's structural gaps
        gaps = review.get("structural_gaps") or []
        criteria["review"] = {"ready_to_bid": review.get("ready_to_bid"),
                              "structural_gaps": gaps, "pass": not gaps}
        if gaps:
            failures.append("the bid is incomplete: " + "; ".join(gaps[:3]))

        approved = not failures
        reason = ("approved" if approved else "refused: " + "; ".join(failures))

        log.info("%s: %s (margin %s%% vs %.1f%%, %d certs, %d past projects, %d gaps)",
                 self.company, "APPROVED" if approved else "REFUSED",
                 criteria["margin"].get("margin_pct", "n/a"), floor,
                 len(certifications), len(past_projects), len(gaps))

        decision = {
            "company": self.company,
            "approved": approved,
            "reason": reason,
            "criteria": criteria,
            "evidence": {
                "certifications": certifications,
                "past_projects": past_projects,
                "projects_served": credentials.get("projects_served"),
                "licenses_supplied": credentials.get("licenses_supplied"),
            },
        }

        rationale, risks = self._write_rationale(decision, compliance, sizing, finance,
                                                 review, session_id, model_name)
        if rationale:
            decision["reason"] = rationale
            decision["verdict"] = reason        # the criteria-based verdict, kept verbatim
        decision["risks"] = risks
        return decision

    def _write_rationale(self, decision, compliance, sizing, finance, review,
                         session_id, model_name):
        """Wording only. The verdict above is already settled and is not revisited."""
        summary = {
            "total_budget": finance.get("total_budget"),
            "one_time_cost": finance.get("one_time_cost"),
            "amc_cost": finance.get("amc_cost"),
            "timeline_weeks": finance.get("timeline_weeks"),
            "sizing_totals": sizing.get("totals") or {},
            "compliance": f"{compliance.get('met')}/{compliance.get('total')}",
            "usecases_not_covered": compliance.get("uncovered_usecases") or [],
            "live_endpoints": len(compliance.get("live_endpoints") or []),
            "review_missing": (review.get("missing") or [])[:5],
        }
        try:
            with self._get_lm_context(model_name, session_id):
                result = dspy.ChainOfThought(ApprovalRationaleSignature)(
                    verdict=json.dumps({"approved": decision["approved"],
                                        "reason": decision["reason"],
                                        "criteria": decision["criteria"]}, indent=2),
                    bid_summary=json.dumps(summary, indent=2))
            parsed = extract_json(result.rationale_result) or {}
        except Exception as e:
            log.warning("%s: could not write an approval rationale (%s); the verdict stands",
                        self.company, e)
            return None, []

        if not isinstance(parsed, dict):
            return None, []
        rationale = str(parsed.get("rationale") or "").strip()
        risks = [str(r) for r in (parsed.get("risks") or [])]
        return (rationale or None), risks


if __name__ == "__main__":
    main(MultiFaceTechHeadAgent)
