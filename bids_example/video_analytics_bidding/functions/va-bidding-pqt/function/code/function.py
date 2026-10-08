"""Pre-qualification for the video-analytics round.

OpenArcade calls this inline inside `POST /bid-jobs/{id}/bids`, once per incoming bid,
before the bid is persisted. It answers one question: does this company clear the bars
the RFP itself sets?

For the Patna tender those bars are written into the document --

    "The Vendor should have any performance benchmarking certificate. NIST certificate
     will be preferred."
    "OEM of VMS should have supplied at least 10,000 cameras Licenses in India or
     globally in qualifying projects."

-- and the concrete thresholds live in `function_settings`, so the same function serves
a different RFP by changing settings rather than code.

Three deliberate choices, all of them about not stalling a round:

**It never sets `bid_rejected`.** Marking a rejected bid is OpenArcade's job when it
hands bids to the evaluator. Writing the marker here as well would double-mark it.

**It runs as a deployment, not a job** (`is_stateful: true`). This function sits inline
in the bidders' own HTTP call, so its latency is their latency. As a stateless function
each submission started a fresh Kubernetes job; five companies submitting within a few
seconds of each other queued five job starts behind the registry's 60-second read
timeout, and OpenArcade answered `POST /bid-jobs/{id}/bids` with a 500 three times in
one round (24 Sep 2026, bid job 880b0745). The bid managers retried and the round
survived, but it cost about a hundred seconds of backoff. A long-lived deployment
answers in well under a second and the queue disappears.

**It never raises.** An exception here surfaces as a 500 inline in the bidder's own HTTP
call, which loses the round a participant -- and evaluation only fires once every
participant has a bid on file, so a single traceback can stall the whole round forever.
A malformed bid is a failed check with a readable reason instead.
"""
import logging
import os
import sys

# The registry runs code/ as the tree root; the local test imports this as
# function.code.function. Putting this file's directory on the path makes the
# vendored import work either way, the same way va-bid-eval does it.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import function_his as his  # noqa: E402  (vendored alongside this file by build.sh)

DEFAULT_CERTIFICATIONS = ["NIST", "benchmarking", "UL"]
DEFAULT_MIN_LICENSES_SUPPLIED = 10000
DEFAULT_MIN_PROJECTS_SERVED = 5


class AIOSv1PolicyRule:

    def __init__(self, rule_id, settings, parameters):
        self.rule_id = rule_id
        self.settings = settings or {}
        self.parameters = parameters or {}

    def _as_int(self, value):
        """Coerce a credential count, or None if it cannot be read as a number."""
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str):
            try:
                return int(float(value.strip().replace(",", "")))
            except ValueError:
                return None
        return None

    # The subject id these records are filed under. One per function rather than one
    # per company: HIS groups by subject, and the company travels on each record, which
    # is what lets the dashboard show pre-qualification company by company while the
    # round still reads as a single pre-qualification story.
    SUBJECT_ID = "va-bidding-pqt"

    def eval(self, parameters, input_data, context):
        input_data = input_data or {}
        his_url = his.base_url(self.settings, input_data.get("bid_job"))
        bid = input_data.get("bid") or {}
        bid_data = bid.get("bid_data") or {}
        company = bid_data.get("company") or bid.get("bid_subject_id")
        bid_job_id = (input_data.get("bid_job") or {}).get("bid_job_id")

        # What this company is being judged on, before any judging -- the same
        # INCOMING_TASK/OUTGOING_RESULT pair every agent files, so the dashboard reads a
        # function's record exactly like an agent's.
        his.report(his_url, self.SUBJECT_ID, "pqt", "INCOMING_TASK", {
            "bid_subject_id": bid.get("bid_subject_id"),
            "bid_status": bid_data.get("bid_status"),
            "credentials": bid_data.get("credentials"),
            "thresholds": self._thresholds(),
        }, company=company, stage="pqt", bid_job_id=bid_job_id)

        try:
            decision = self._decide(input_data)
        except Exception as e:
            # Last line of defence. Rejecting is the safe failure: an accepted bid the
            # evaluator then cannot score would distort the round, while a rejection is
            # recorded, visible, and still lets the round reach a winner.
            logging.exception("%s: unexpected error, rejecting bid", self.rule_id)
            decision = {"accepted": False,
                        "reason": f"pre-qualification could not be completed: {e}"}

        his.report(his_url, self.SUBJECT_ID, "pqt", "OUTGOING_RESULT", decision,
                   company=company, stage="pqt", bid_job_id=bid_job_id,
                   note="accepted" if decision.get("accepted") else "rejected")
        return decision

    def _thresholds(self):
        """The bar this function holds every bid to, as the dashboard shows it."""
        return {
            "required_certifications_any_of": list(
                self.settings.get("required_certifications_any_of") or DEFAULT_CERTIFICATIONS),
            "min_licenses_supplied": self.settings.get(
                "min_licenses_supplied", DEFAULT_MIN_LICENSES_SUPPLIED),
            "min_projects_served": self.settings.get(
                "min_projects_served", DEFAULT_MIN_PROJECTS_SERVED),
        }

    def _decide(self, input_data):
        bid = input_data.get("bid") or {}
        bid_data = bid.get("bid_data") or {}
        subject = bid.get("bid_subject_id", "<unknown>")

        # A decline carries no priced content to judge. Rejecting it would confuse two
        # distinct outcomes in the audit trail -- "would not do the work" and "not
        # allowed to" -- so it passes through. The evaluator excludes declines on
        # bid_status regardless, so nothing unqualified can win this way.
        if str(bid_data.get("bid_status", "")).lower() == "declined":
            logging.info("%s: %s declined; passing through un-judged", self.rule_id, subject)
            return {"accepted": True, "reason": "declining bid, not pre-qualified",
                    "checks": [{"check": "bid_status", "required": "a priced bid",
                                "found": "declined", "passed": True,
                                "note": "passed through un-judged; the evaluator excludes "
                                        "declines on bid_status regardless"}]}

        required_any = self.settings.get("required_certifications_any_of") or DEFAULT_CERTIFICATIONS
        min_licenses = self.settings.get("min_licenses_supplied", DEFAULT_MIN_LICENSES_SUPPLIED)
        min_projects = self.settings.get("min_projects_served", DEFAULT_MIN_PROJECTS_SERVED)

        credentials = bid_data.get("credentials")
        if not isinstance(credentials, dict):
            return {
                "accepted": False,
                "reason": ("no credentials block on the bid; the RFP requires a benchmarking "
                           "certificate and a minimum supplied-licence track record"),
                "checks": [{"check": "credentials", "required": "a credentials block",
                            "found": type(credentials).__name__, "passed": False}],
            }

        failures = []
        # Every check, passed or failed, with what was required and what was found. The
        # bid only carries the failures as prose; this is what makes a rejection
        # explainable in the dashboard without opening a pod log.
        checks = []

        # 1. Certification. Substring, case-insensitive: a company states "NIST FRVT"
        #    where the RFP says "NIST", and both should match.
        held = [str(c) for c in (credentials.get("certifications") or [])]
        held_lower = " | ".join(held).lower()
        matched = [want for want in required_any if str(want).lower() in held_lower]
        if not matched:
            failures.append(
                f"holds no accepted certification (has {held or 'none'}; "
                f"RFP accepts any of {list(required_any)})"
            )
        checks.append({"check": "certification", "required": f"any of {list(required_any)}",
                       "found": held or "none", "passed": bool(matched)})

        # 2. Supplied-licence track record.
        supplied = self._as_int(credentials.get("licenses_supplied"))
        if supplied is None:
            failures.append("licenses_supplied is missing or not a number")
        elif supplied < min_licenses:
            failures.append(f"licenses supplied {supplied} is below the RFP bar of {min_licenses}")
        checks.append({"check": "licenses_supplied", "required": f">= {min_licenses}",
                       "found": supplied, "passed": supplied is not None and supplied >= min_licenses})

        # 3. Projects served.
        projects = self._as_int(credentials.get("projects_served"))
        if projects is None:
            failures.append("projects_served is missing or not a number")
        elif projects < min_projects:
            failures.append(f"projects served {projects} is below the minimum of {min_projects}")
        checks.append({"check": "projects_served", "required": f">= {min_projects}",
                       "found": projects, "passed": projects is not None and projects >= min_projects})

        if failures:
            reason = "; ".join(failures)
            logging.info("%s: rejecting %s -- %s", self.rule_id, subject, reason)
            return {"accepted": False, "reason": reason, "checks": checks}

        reason = (f"certification {matched[0]} accepted; {supplied} licences supplied "
                  f"across {projects} projects")
        logging.info("%s: accepting %s -- %s", self.rule_id, subject, reason)
        return {"accepted": True, "reason": reason, "checks": checks}
