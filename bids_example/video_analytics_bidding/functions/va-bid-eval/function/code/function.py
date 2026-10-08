"""Scoring the video-analytics round and naming a winner.

OpenArcade calls this once per bid job, on a background thread, after every participant
has a bid on file. It scores the surviving bids on four dimensions and returns one
winner.

    (a) budget    -- cheapest wins, ranked within the field
    (b) sizing    -- leanest wins, cpu/ram/disk/gpu ranked separately then weighted
    (c) compliance-- met / total of the RFP's requirements
    (d) endpoint  -- each company's live endpoints called with a shared image set and
                     compared against a shared ground truth

Dimension (d) is the one that reaches back out: the AI Compliance Agents registered live
functions while preparing their bids, and this is where those get exercised. The calls
go through `AgentFunctions`, the same registry client the rest of the platform uses,
vendored into this package because the registry runs `function/code/` as an isolated
tree with no access to the repo.

This runs as a deployment, not a job (`is_stateful: true`). OpenArcade allows the
evaluator a 60-second read timeout, and the platform's job path does not fit inside it:
the executor accepts `POST /create_job`, returns an id, and the registry then polls a
job that never resolves -- on 24 Sep 2026 the executor logged `Unexpected error in
listener: Timeout reading from socket` while the registry polled job ids the executor
answered "not found" for, and a call that should take seconds ran past 400 with no
result. The same cluster served 15 stateful `call_function` requests in under a second
each. So both this function and the PQT run as long-lived deployments.

Two failure modes shape almost every defensive choice below. This runs on a background
thread, so an uncaught exception means no winner is ever chosen and the Xchange task
hangs in "bidding" with no timeout. And evaluation cannot be retried. So a bad field
costs a company points, never the round.
"""
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import function_his as his  # noqa: E402  (vendored alongside this file by build.sh)
import va_bid_utils as V  # noqa: E402  (vendored alongside this file by build.sh)

DEFAULT_WEIGHTS = {"cpu": 0.2, "ram": 0.2, "disk": 0.1, "gpu": 0.5}


class AIOSv1PolicyRule:

    def __init__(self, rule_id, settings, parameters):
        self.rule_id = rule_id
        self.settings = settings or {}
        # The caller's read timeout is what these exist for: OpenArcade allows the
        # evaluator 60 seconds, and a serial probe of two companies at ten images each
        # takes more than twice that. Both are settings because the right values depend
        # on the deployment, not on this function.
        self.probe_workers = int(self.settings.get("probe_workers") or 6)
        self.probe_budget_s = float(self.settings.get("probe_budget_seconds") or 45)

        self.parameters = parameters or {}

        # How each company's endpoint score was arrived at, filled in during scoring so
        # the HIS record can show 7/10 rather than only 70. Per call, not per instance
        # in spirit -- the executor builds a fresh rule per call, so there is nothing to
        # reset between rounds.
        self.endpoint_detail = {}

    # The subject id these records are filed under, matching the agents' convention:
    # one subject per participant, and the round is reconstructed from the bid_job_id
    # every record carries.
    SUBJECT_ID = "va-bid-eval"

    # --- entry point -------------------------------------------------------

    def eval(self, parameters, input_data, context):
        input_data = input_data or {}
        bid_job = input_data.get("bid_job") or {}
        his_url = his.base_url(self.settings, bid_job)
        bid_job_id = bid_job.get("bid_job_id")

        # What arrived, before any scoring. Until now the evaluator's whole reasoning
        # lived in a pod log: the dashboard could show the scores it produced but never
        # the bids it saw, the weights it applied or why a bid was excluded.
        evaluation = (bid_job.get("bid_job_metadata") or {}).get("evaluation") or {}
        his.report(his_url, self.SUBJECT_ID, "evaluator", "INCOMING_TASK", {
            "bids_received": len(input_data.get("bids") or []),
            "bid_subject_ids": [b.get("bid_subject_id") for b in (input_data.get("bids") or [])],
            "weights": evaluation.get("weights") or self.settings.get("weights") or DEFAULT_WEIGHTS,
            "sample_images": len(evaluation.get("sample_images")
                                 or self.settings.get("sample_images") or []),
            "probe_workers": self.probe_workers,
            "probe_budget_seconds": self.probe_budget_s,
        }, stage="evaluation", bid_job_id=bid_job_id)

        try:
            result = self._evaluate(input_data)
        except Exception as e:
            # Nothing above us catches this usefully: OpenArcade logs it and the round
            # never resolves. Returning a shaped response at least records why.
            logging.exception("%s: evaluation failed", self.rule_id)
            result = {"status": "evaluation_failed", "result_data": {"error": str(e)}}

        # The verdict and everything behind it: every dimension per company, the
        # endpoint tallies the percentages came from, the exclusions and the tie break.
        payload = dict(result.get("result_data") or {})
        payload["status"] = result.get("status")
        payload["winner_subject_id"] = result.get("winner_subject_id")
        payload["endpoint_detail"] = self.endpoint_detail
        payload["dimensions"] = ("budget and sizing are ranked within the field; "
                                 "compliance is met/total; endpoint is correct/total. "
                                 "Each is out of 100 and the total is their sum, out of 400.")
        his.report(his_url, self.SUBJECT_ID, "evaluator", "OUTGOING_RESULT", payload,
                   stage="evaluation", bid_job_id=bid_job_id,
                   note=result.get("status"))
        return result

    def _evaluate(self, input_data):
        bid_job = input_data.get("bid_job") or {}
        all_bids = input_data.get("bids") or []

        survivors, excluded = self._filter(all_bids)
        logging.info("%s: %d bids, %d surviving, %d excluded",
                     self.rule_id, len(all_bids), len(survivors), len(excluded))

        if not survivors:
            return {"status": "no_valid_bids",
                    "result_data": {"excluded": excluded,
                                    "reason": "every bid was declined or rejected"}}

        evaluation = (bid_job.get("bid_job_metadata") or {}).get("evaluation") or {}
        weights = evaluation.get("weights") or self.settings.get("weights") or DEFAULT_WEIGHTS
        sample_images = evaluation.get("sample_images") or self.settings.get("sample_images") or []

        budget = V.budget_scores(survivors)
        sizing = V.weighted_sizing_scores(survivors, weights)
        endpoint = self._score_endpoints(survivors, sample_images, bid_job)

        scored = {}
        for bid in survivors:
            subject = bid.get("bid_subject_id")
            bid_data = bid.get("bid_data") or {}
            compliance = V.compliance_score(bid_data)
            scored[subject] = {
                "budget": budget.get(subject, 0.0),
                "sizing": sizing.get(subject, 0.0),
                "compliance": compliance,
                "endpoint": endpoint.get(subject, 0.0),
                "total": V.total_score(budget.get(subject, 0.0), sizing.get(subject, 0.0),
                                       compliance, endpoint.get(subject, 0.0)),
                "total_budget": bid_data.get("total_budget"),
                "company": bid_data.get("company"),
            }

        winner, tie_break = V.pick_winner(scored)
        if winner is None:
            return {"status": "no_valid_bids",
                    "result_data": {"excluded": excluded, "reason": "no bid could be scored"}}

        logging.info("%s: winner %s with %s", self.rule_id, winner, scored[winner]["total"])
        return {
            "winner_subject_id": winner,
            "status": "resolved",
            "result_data": {
                "scores": scored,
                "excluded": excluded,
                "tie_break": tie_break,
                "weights": weights,
                "sample_image_count": len(sample_images),
                "reason": "highest total of budget + sizing + compliance + endpoint",
            },
        }

    # --- step 1: filter ----------------------------------------------------

    def _filter(self, bids):
        """Survivors and an audit trail of who was dropped and why.

        Excluded bids take no part in any percentile calculation -- the field is the
        survivors alone -- so a declined bid's price cannot drag a rival's budget rank.
        """
        survivors, excluded = [], []
        for bid in bids:
            bid_data = bid.get("bid_data") or {}
            subject = bid.get("bid_subject_id")
            if str(bid_data.get("bid_status", "")).lower() == "declined":
                excluded.append({"subject_id": subject, "why": "declined",
                                 "detail": bid_data.get("decline_reason", "")})
                continue
            # Set by OpenArcade when pre-qualification rejected the bid. Never written
            # by this example's own code.
            if bid_data.get("bid_rejected"):
                excluded.append({"subject_id": subject, "why": "bid_rejected",
                                 "detail": bid_data.get("pqt_reason", "")})
                continue
            survivors.append(bid)
        return survivors, excluded

    # --- step 3d: live endpoints ------------------------------------------

    def _score_endpoints(self, bids, sample_images, bid_job, agent_functions=None):
        """Call each company's registered endpoints and score them against ground truth.

        A company that reported no endpoints scores 0 rather than being excluded --
        failing to stand up a stand-in is a weakness, not a disqualification.
        """
        scores = {}
        if not sample_images:
            logging.warning("%s: no sample images on the bid job; endpoint dimension is 0 for all",
                            self.rule_id)
            return {bid.get("bid_subject_id"): 0.0 for bid in bids}

        af, owned = agent_functions, False
        if af is None:
            af, owned = self._open_registry(bid_job)
            if af is None:
                return {bid.get("bid_subject_id"): 0.0 for bid in bids}

        probed = set()
        try:
            for bid in bids:
                subject = bid.get("bid_subject_id")
                endpoints = (bid.get("bid_data") or {}).get("live_endpoints") or []
                probed.update(e.get("function_id") for e in endpoints
                              if isinstance(e, dict) and e.get("function_id"))
                if not endpoints:
                    logging.info("%s: %s reported no live endpoints; scoring 0", self.rule_id, subject)
                    scores[subject] = 0.0
                    self.endpoint_detail[subject] = {
                        "correct": 0, "total": 0, "endpoints": [],
                        "why": "the bid reported no live endpoints"}
                    continue
                correct, total = self._probe(af, subject, endpoints, sample_images)
                scores[subject] = V.endpoint_score(correct, total)
                self.endpoint_detail[subject] = {
                    "correct": correct, "total": total,
                    "endpoints": [e.get("function_id") for e in endpoints
                                  if isinstance(e, dict)]}
                logging.info("%s: %s answered %d/%d -> %s", self.rule_id, subject,
                             correct, total, scores[subject])
        finally:
            # Each endpoint is a live deployment held for the round. Nothing else will
            # reclaim them, so a round that does not release them leaves a pod per
            # company running until someone notices.
            for function_id in probed:
                try:
                    af.remove(function_id, remove_deployment=True)
                except Exception as e:
                    logging.warning("%s: could not release the deployment for %s (%s)",
                                    self.rule_id, function_id, e)
            if owned:
                try:
                    af.shutdown()   # the worker pool started in __init__ will not exit on its own
                except Exception:
                    logging.warning("%s: AgentFunctions shutdown failed", self.rule_id)
        return scores

    def _open_registry(self, bid_job):
        try:
            from agents_functions import AgentFunctions
        except ImportError:
            logging.warning("%s: agents_functions is not vendored into this package; "
                            "endpoint dimension scores 0 for everyone", self.rule_id)
            return None, False
        # The bid job first, then settings, then the environment.
        #
        # `function_settings` is the obvious home for this and it does not work: a
        # stateful function runs in a deployment, and `create_deployment` sends the
        # function id, replicas and tags but not the settings, so the manifest's
        # `functions_registry_url` never reaches this process. The registry holds it and
        # the pod has never seen it -- which is why the endpoint dimension scored 0 for
        # everyone in bid jobs 170a2315 and 9a9b9f38 while the setting sat correctly in
        # the registry all along.
        #
        # The bid job does reach us, so the url travels on bid_job_metadata.evaluation
        # alongside the sample images. The settings and environment lookups stay as
        # fallbacks for a stateless deployment of this same function.
        evaluation = (bid_job.get("bid_job_metadata") or {}).get("evaluation") or {}
        registry = (evaluation.get("functions_registry_url")
                    or self.settings.get("functions_registry_url")
                    or os.environ.get("FUNCTION_REGISTRY_URL"))
        if not registry:
            logging.warning("%s: no functions registry url on the bid job, in settings or in "
                            "the environment; endpoint dimension scores 0", self.rule_id)
            return None, False
        try:
            af = AgentFunctions(
                functions_registry_url=registry,
                num_workers=self.probe_workers,
                # The registry 404s on an executor it does not have ("Executor not
                # found", surfaced as a 502). The name belongs to the deployment, not
                # to this function, so it is a setting with the platform's default.
                executor_id=(self.settings.get("function_executor_id")
                             or os.environ.get("FUNCTION_EXECUTOR_ID")
                             or "executor-001"),
                # Must match what the Compliance Agent used when it published the
                # endpoint (function_publisher.DEPLOYMENT_SCOPE), because AgentFunctions
                # composes a deployment name from it. Scoping this per round would
                # address a deployment that does not exist and stand up a second copy,
                # paying exactly the startup cost that being stateful avoids.
                unique_parameter="va-live",
            )
            return af, True
        except Exception as e:
            logging.warning("%s: could not reach the function registry (%s); "
                            "endpoint dimension scores 0 for everyone", self.rule_id, e)
            return None, False

    def _probe(self, af, subject, endpoints, sample_images):
        """One call per endpoint per image, run concurrently. A failure counts as wrong.

        Serial probing is what stopped a round completing: OpenArcade calls this
        evaluator with a 60-second read timeout, each registry call takes ~7 seconds,
        and two companies at ten images each is twenty calls -- around 140 seconds. The
        registry timed out, OpenArcade logged "Evaluator function failed" and does not
        retry, so the bid job stayed unevaluated for good.

        So every probe is dispatched at once through the worker pool and collected
        against a shared deadline. Whatever has not answered by then counts wrong, the
        same as any other failure: returning a slightly harsher score beats returning
        nothing at all and stranding the round.
        """
        correct = total = 0
        deadline = time.monotonic() + self.probe_budget_s

        for endpoint in endpoints:
            function_id = (endpoint or {}).get("function_id")
            if not function_id:
                continue
            try:
                af.add(function_id)      # mandatory: call() raises ValueError without it
            except Exception as e:
                # Every image for this endpoint is now unanswerable, and each counts
                # against the company -- an endpoint it claimed but cannot serve.
                logging.warning("%s: %s could not resolve %s (%s); counting %d wrong",
                                self.rule_id, subject, function_id, e, len(sample_images))
                total += len(sample_images)
                continue

            # Dispatch first, collect second. AgentFunctions gives every call its own
            # job name, so concurrent calls do not collide.
            pending = []
            for image in sample_images:
                total += 1
                try:
                    handle = af.execute_async(function_id,
                                              {"image_url": image.get("url", ""),
                                               "image_name": image.get("name", "")})
                    pending.append((image, handle))
                except Exception as e:
                    logging.info("%s: %s could not be dispatched for %s (%s); counting wrong",
                                 self.rule_id, function_id, image.get("name"), e)

            for image, handle in pending:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    logging.warning("%s: %s ran out of probe budget on %s; counting wrong",
                                    self.rule_id, function_id, image.get("name"))
                    continue
                try:
                    out = handle.wait(timeout=remaining)
                    answer = out.get("result") if isinstance(out, dict) else None
                    if isinstance(answer, bool) and answer == bool(image.get("ground_truth")):
                        correct += 1
                    elif not isinstance(answer, bool):
                        logging.info("%s: %s returned a non-boolean %r for %s",
                                     self.rule_id, function_id, answer, image.get("name"))
                except Exception as e:
                    logging.info("%s: %s failed on %s (%s); counting wrong",
                                 self.rule_id, function_id, image.get("name"), e)
        return correct, total
