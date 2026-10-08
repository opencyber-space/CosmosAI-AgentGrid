"""CamFaceSolution -- AI Compliance Agent.

The first subordinate the Bid Manager consults, and the one that can end the bid before
it starts. It reads the RFP, works out what the buyer is actually asking for, and
compares that against what this company's `config.yaml` says it can deliver.

Two outputs matter downstream:

  * a per-requirement verdict with a "met N of M" summary -- the evaluator's compliance
    dimension is that fraction, so it has to be honest rather than flattering
  * up to two **live** use-case endpoints, registered into the function registry while
    this agent runs, which the evaluator calls later with a shared image set

It can also decline on the company's behalf, for two distinct reasons: the catalogue
does not cover the use cases the RFP needs, or the licence count falls outside what this
company supplies. Both come from `config.yaml` -- nothing in this file knows which
companies are meant to decline.

Requirements are extracted from the RFP by the model, not by a regex parser. The
supplied documents are real tender extracts, a thousand-odd lines of numbered clauses
and table cells, and a rule-based parser would only ever work on the one document it was
written against.
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
from common import (company_config, endpoint_names, function_publisher,  # noqa: E402
                    his_logger, rfp_requirements, spec_env)

log = logging.getLogger(__name__)

COMPANY = "CamFaceSolution"
ROLE = "ai_compliance"


class ComplianceVerdictSignature(dspy.Signature):
    """
    ### ROLE
    You are the AI Compliance Agent for a Video Analytics company.

    ### TASK
    Decide, for each requirement the RFP states, whether this company meets it. Judge on
    the whole dossier given, not on one part of it:

      * `usecases` -- what the product does, with operating conditions (indoor/outdoor,
        camera height, population density, frames, resolution, night capability, lux)
        and accuracy figures.
      * `capabilities` -- the product's stated behaviour: matching modes, crowd face
        counts, pose tolerance in degrees, search latency and gallery size, enrolment
        modes, colour and night modes, codecs, alerting, integrations, mobile apps.
      * `platform` -- model training, annotation, benchmarking, dashboards, licensing
        modes and privacy posture.
      * `credentials` -- certifications, projects served, licences supplied, past
        projects.
      * `licensing` and `hardware` -- the supported licence range and what the product
        runs on.

    ### HOW TO JUDGE
    A requirement is `met: true` when the dossier states something that satisfies it,
    including when the dossier is more capable than the requirement asks. Compare
    numbers as numbers: a stated tolerance of yaw +-45 degrees meets a requirement for
    +-40; a 3 second search meets "under 5 seconds"; a 2 million gallery meets "up to 1
    million". A capability listed as supported meets a requirement to support it, even
    if the wording differs -- "1:N" and "one-to-many" are the same thing.

    A requirement is `met: false` when the dossier contradicts it or is silent on it.
    Say which field you looked at and what it said. Do not mark something met because it
    seems likely for a vendor of this kind; judge the dossier, not the industry.

    Be honest in both directions. Overstating coverage produces a bid the company cannot
    deliver. Understating it -- marking `false` for something the dossier plainly states
    in different words -- loses a round the company should have won.

    ### OUTPUT
    Output EXACTLY a JSON block, one entry per requirement, echoing each requirement
    verbatim:
    {"points": [{"requirement": "string", "met": bool, "reason": "string"}]}
    """
    requirements = dspy.InputField(desc="Requirements extracted from the RFP, one per line")
    company_catalogue = dspy.InputField(desc="This company's full dossier: usecases, capabilities, platform, credentials, licensing and hardware")
    verdict_result = dspy.OutputField(desc="JSON block of per-requirement verdicts")


class CamFaceSolutionAiComplianceAgent:

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

    # --- framework hooks ---------------------------------------------------

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
        session_id = data.get("session_id", task.task_id)
        model_name = data.get("model_name", self.default_model)
        rfp_url = data.get("rfp_url")

        try:
            report = self._assess(rfp_url, session_id, model_name)
        except Exception as e:
            # The Bid Manager turns any error here into a declining bid. Returning a
            # shaped report rather than raising means the reason reaches the bid.
            log.exception("%s: compliance assessment failed", self.company)
            report = {
                "points": [], "met": 0, "total": 0, "usecases_required": [],
                "live_endpoints": [],
                "decline_reason": f"compliance assessment failed: {e}",
                "decline_stage": "compliance",
            }

        self._report("OUTGOING_RESULT", report, stage=data.get("stage"),
                     bid_job_id=data.get("bid_job_id"),
                     destination_id=f"{self.slug}-bid-manager")
        return AgentResult(task_id=task.task_id, job_output=report)

    # --- assessment --------------------------------------------------------

    def _assess(self, rfp_url, session_id, model_name):
        if not rfp_url:
            raise ValueError("no rfp_url supplied; the compliance agent cannot assess without the RFP")

        asked = self._asked_of_the_rfp(rfp_url, session_id, model_name)
        usecases_required = asked.get("usecases") or []
        total_licenses = int(asked.get("total_licenses") or 0)
        requirements = asked.get("requirements") or []
        benchmarked = asked.get("benchmarked_usecases") or []

        log.info("%s: RFP asks for %d use cases, %d licences, %d requirements",
                 self.company, len(usecases_required), total_licenses, len(requirements))

        # --- decline path 1: the licence count is outside what we supply ---
        licensing = self.config["licensing"]
        if total_licenses and not company_config.licence_count_supported(self.config, total_licenses):
            return self._decline(
                "licensing",
                f"RFP requires {total_licenses} licences; this company supplies between "
                f"{licensing['min_licenses']} and {licensing['max_licenses']}",
                usecases_required, total_licenses)

        # --- decline path 2: the catalogue does not cover the work ---
        coverage, uncovered = self._coverage(usecases_required)
        if not coverage:
            return self._decline(
                "compliance",
                "the company catalogue covers none of the use cases this RFP requires: "
                + ", ".join(u.get("name", u.get("id", "?")) for u in usecases_required[:6]),
                usecases_required, total_licenses)

        needs_outdoor = any(u.get("outdoor") for u in usecases_required)
        if needs_outdoor and not any(
                company_config.serves_outdoor(self.config, uc_id) for uc_id in coverage):
            return self._decline(
                "compliance",
                "this RFP is an outdoor deployment and every use case in the company "
                "catalogue is indoor-only",
                usecases_required, total_licenses)

        # --- per-requirement verdicts ---
        points = self._align_verdicts(requirements, self._verdicts(requirements, session_id, model_name))
        met = sum(1 for p in points if p.get("met"))
        total = len(requirements)
        log.info("%s: compliance %d/%d, covering %d of %d use cases",
                 self.company, met, total, len(coverage), len(usecases_required))

        # --- live endpoints ---
        live_endpoints, endpoint_failures = self._offer_endpoints(benchmarked, coverage)

        return {
            "company": self.company,
            "points": points,
            "met": met,
            "total": total,
            "usecases_required": usecases_required,
            "total_licenses": total_licenses,
            # Always "shared_function": there is no other source. It stays on the bid
            # so a reviewer can confirm at a glance that every fraction on this job was
            # scored out of the same list.
            "requirements_source": asked.get("requirements_source", "unknown"),
            "covered_usecases": coverage,
            "uncovered_usecases": uncovered,
            "live_endpoints": live_endpoints,
            "endpoint_failures": endpoint_failures,
            "decline_reason": None,
        }

    def _decline(self, stage, reason, usecases_required, total_licenses):
        log.info("%s: declining at %s -- %s", self.company, stage, reason)
        return {
            "company": self.company,
            "points": [], "met": 0, "total": 0,
            "usecases_required": usecases_required,
            "total_licenses": total_licenses,
            "live_endpoints": [],
            "decline_reason": reason,
            "decline_stage": stage,
        }

    def _asked_of_the_rfp(self, rfp_url, session_id, model_name):
        """What this RFP demands -- the same answer every company gets.

        `va-rfp-requirements` owns the list and caches it against the url, so all five
        bidders are judged against identical requirements and the extraction is paid for
        once. There is deliberately no local fallback: extracting here instead produced
        a different list per company, which is how met/total came to compare 0/16
        against 1/70 on one RFP. A company that cannot reach the function declines with
        that as the reason, which is honest, visible, and fixable -- unlike a bid scored
        against a private requirement list nobody else was judged on.
        """
        return rfp_requirements.fetch(rfp_url, self.subject, model_name=model_name)

    @staticmethod
    def _align_verdicts(requirements, points):
        """One verdict per RFP requirement, in the RFP's order.

        The denominator has to be the RFP's requirement count and nothing else. Taking
        it from the verdicts instead -- `total = len(points)` -- lets the model set the
        denominator by answering about fewer clauses than it was given, so a company
        whose model skipped half the list would score out of half as many and look
        stronger for it. Shared requirements fix the numerator's fairness; this fixes
        the denominator's.

        A requirement with no verdict is unmet: not answered is not met.
        """
        def normalise(text):
            return " ".join(str(text or "").split()).lower()

        usable = [p for p in points if isinstance(p, dict)]

        # Pass 1: the model echoed the clause back, so match on it and mark it spent.
        spent = [False] * len(usable)
        by_text = {}
        for position, point in enumerate(usable):
            key = normalise(point.get("requirement"))
            if key and key not in by_text:
                by_text[key] = position

        matched = {}
        for index, requirement in enumerate(requirements):
            position = by_text.get(normalise(requirement))
            if position is not None and not spent[position]:
                spent[position] = True
                matched[index] = usable[position]

        # Pass 2: whatever is left is a paraphrase. Order is the only link remaining,
        # and it is the order the requirements were sent in.
        spare = (usable[i] for i, used in enumerate(spent) if not used)
        for index in range(len(requirements)):
            if index not in matched:
                matched[index] = next(spare, None)

        aligned = []
        for index, requirement in enumerate(requirements):
            point = matched.get(index)
            if point is None:
                aligned.append({"requirement": requirement, "met": False,
                                "reason": "no verdict produced for this requirement"})
            else:
                aligned.append({"requirement": requirement,
                                "met": bool(point.get("met")),
                                "reason": str(point.get("reason") or "")})
        return aligned

    def _dossier(self):
        """Everything about this company a requirement could be judged against.

        Passing only `usecases` is what kept met at 0. The RFP asks about pose tolerance,
        gallery size, search latency, enrolment, codecs, integrations, certifications and
        licensing modes; none of that is in the use-case list, so the model had nothing to
        confirm and answered "the catalogue does not mention it" for 37 of 37
        requirements (bid job 9a9b9f38). It was judging honestly -- it simply had not
        been shown the evidence.
        """
        return {key: self.config[key] for key in
                ("usecases", "capabilities", "platform", "credentials", "licensing", "hardware")
                if key in self.config}

    def _verdicts(self, requirements, session_id, model_name):
        """One verdict per RFP requirement. The met/total fraction is scored later."""
        if not requirements:
            log.warning("%s: the RFP yielded no checkable requirements; compliance will score 0",
                        self.company)
            return []
        with self._get_lm_context(model_name, session_id):
            result = dspy.ChainOfThought(ComplianceVerdictSignature)(
                requirements="\n".join(f"- {r}" for r in requirements),
                company_catalogue=json.dumps(self._dossier(), indent=2),
            )
        parsed = extract_json(result.verdict_result) or {}
        points = parsed.get("points") if isinstance(parsed, dict) else None
        if not isinstance(points, list):
            log.warning("%s: verdicts came back malformed; treating every requirement as unmet",
                        self.company)
            return [{"requirement": r, "met": False, "reason": "no verdict produced"} for r in requirements]
        return [p for p in points if isinstance(p, dict)]

    def _coverage(self, usecases_required):
        """Which required use cases this company's catalogue can serve.

        Matching is by id first, then by distinctive word overlap -- the model names use
        cases in the buyer's words, which rarely match the catalogue's ids exactly.

        The word overlap ignores the vocabulary every video-analytics use case shares.
        Without that, "Vehicle over-speeding **detection**" matches "multi-face
        **detection** in crowds" and the company claims to cover work it cannot do --
        which is worse than declining, because it produces a bid that wins and then
        cannot be delivered. The best overlap wins rather than the first, so ordering
        in `config.yaml` cannot change the answer.
        """
        catalogue = {uc["id"]: uc for uc in self.config["usecases"]}
        covered, uncovered = [], []

        for required in usecases_required:
            req_id = (required.get("id") or "").strip().lower()
            req_name = (required.get("name") or "").strip().lower()

            if req_id in catalogue:
                match = req_id
            else:
                req_words = self._distinctive_words(req_id, req_name)
                best, best_overlap = None, 0
                for uc_id, uc in catalogue.items():
                    own = self._distinctive_words(uc_id, uc["name"].lower())
                    overlap = len(req_words & own)
                    if overlap > best_overlap:
                        best, best_overlap = uc_id, overlap
                match = best

            if match:
                if match not in covered:
                    covered.append(match)
            else:
                uncovered.append(required.get("name") or req_id)

        return covered, uncovered

    # Words shared by most video-analytics use-case names. Matching on these says
    # nothing about whether two use cases are the same capability.
    GENERIC_WORDS = frozenset({
        "detection", "detect", "detecting", "system", "systems", "analytics", "analysis",
        "video", "based", "camera", "cameras", "management", "monitoring", "automatic",
        "automated", "real", "time", "using", "with", "from", "intelligent", "smart",
        "solution", "module", "feature", "live", "advanced",
    })

    @classmethod
    def _distinctive_words(cls, identifier, name):
        words = set(identifier.replace("-", "_").split("_"))
        words |= set(name.replace("-", " ").replace("/", " ").split())
        return {w for w in words if len(w) > 3 and w not in cls.GENERIC_WORDS}

    def _offer_endpoints(self, benchmarked, coverage):
        """Put this company's live endpoints on the bid, for the evaluator to call.

        The endpoints themselves are built, uploaded and warmed before the round by
        functions/build_endpoints.py, upload.sh and warmup.sh. This agent no longer
        publishes them -- a registry upload and a first-ever deployment creation inside
        the bidding window is the cold start that broke bid job 9db948a0, and what each
        endpoint answers is no longer readable from here anyway: it is packaged into the
        function from a file that is not in this repo.

        What is still decided here, per round, is which of them to offer: the use cases
        the RFP puts under live benchmarking, intersected with what this company
        declares, capped so every company brings the same number to the bake-off.

        An endpoint that fails to answer is left off the bid. That costs this company
        endpoint score; it does not fail the bid, because a stand-in failing to deploy is
        not a reason to lose a tender.
        """
        endpoints_config = self.config["live_endpoints"]
        declared = endpoint_names.declared_endpoints(self.config)
        max_endpoints = endpoints_config.get("max_live_endpoints", 2)

        wanted = [uc_id for uc_id in benchmarked if uc_id in declared]
        if not wanted:
            wanted = [uc_id for uc_id in coverage if uc_id in declared]

        published, failures = function_publisher.resolve_usecase_endpoints(
            company_slug=self.slug,
            usecase_ids=wanted,
            declared=declared,
            max_endpoints=max_endpoints,
        )
        log.info("%s: %d live endpoint(s) verified, %d failed",
                 self.company, len(published), len(failures))
        return published, failures

if __name__ == "__main__":
    main(CamFaceSolutionAiComplianceAgent)
