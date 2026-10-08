"""Bring every stateful function deployment up before a round needs it.

A freshly uploaded function has no deployment. The first caller creates one, and that
caller then waits for a container to pull, `pip install` the function's requirements and
bind its Flask app. For `va-rfp-requirements` that install is dspy, litellm, numpy,
pdfplumber and their dependencies -- minutes, not seconds.

Nothing in the round has minutes. On 24 Sep 2026 that single cold start broke three
different things in one round (bid job 9db948a0):

  * `va-bidding-pqt` -- `POST /bid-jobs/{id}/bids` answered 500 twice before the pod
    served; the bid managers' retries covered it.
  * `va-rfp-requirements` -- the compliance agents' call hit `/execute` while the pod
    was still installing, so they fell back to extracting locally and the denominators
    diverged again (37 and 26 against the function's own 42).
  * `va-bid-eval` -- OpenArcade allows 60 seconds and the deployment was not up inside
    it, so the round never resolved.

Worse, the registry reports a deployment live before the app inside it is serving: the
SDK's ping loop breaks on `success`, and `/execute` then fails to connect. So waiting for
the ping is not enough -- this waits until the function actually answers a call.

Run it after `upload.sh` and before any round. It is idempotent: a deployment that is
already serving is left alone and the script returns immediately.
"""
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from agents_functions import AgentFunctions  # noqa: E402

# Deployment scope must match whoever calls it in a round, or we warm a pod nobody uses
# and the real caller still pays the cold start:
#   - OpenArcade calls the pqt and the evaluator under "orcade"
#   - the compliance agents call va-rfp-requirements under "va-live", and the evaluator
#     calls the companies' endpoints under "va-live" too
#     (nodes/common/function_publisher.DEPLOYMENT_SCOPE)
SHARED = [
    ("va-bidding-pqt:1.2-stable", "orcade", {"bid_job": {}, "bid": {}}),
    ("va-bid-eval:1.3-stable", "orcade", {"bid_job": {}, "bids": []}),
    ("va-rfp-requirements:1.0-stable", "va-live", {"rfp_url": ""}),
]


def targets():
    """The shared functions, plus one live endpoint per company per declared use case.

    The endpoints are warmed here because nothing else will: the AI Compliance Agent no
    longer publishes them, so the first caller is the evaluator, inside OpenArcade's
    60-second budget, with no retry. Ten cold starts there lose the whole endpoint
    dimension for the round.

    The list comes from build_endpoints.py so that what is built, uploaded, warmed and
    deleted is one list rather than four guesses at the same naming rule.
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from build_endpoints import endpoint_ids        # noqa: E402

    warmed = list(SHARED)
    for function_id in endpoint_ids():
        # An empty image name is answered with the endpoint's default verdict rather
        # than refused, which is all this needs: a reply of any kind proves the pod is
        # serving. Nothing is scored and no answer is cached.
        warmed.append((function_id, "va-live",
                       {"image_name": "", "image_url": ""}))
    return warmed

DEADLINE_S = float(os.environ.get("WARMUP_DEADLINE_SECONDS", "600"))
RETRY_S = 10.0


def warm(function_id, scope, probe, registry, executor_id):
    """Call the function until it answers, or give up loudly.

    The probe payloads are deliberately empty. Every one of these functions is written
    to answer a malformed request with a shaped refusal rather than an exception, so a
    reply of any kind -- including "no_rfp_url" -- proves the pod is serving, which is
    the only thing being tested here. Nothing is cached and no model is called.
    """
    af = AgentFunctions(functions_registry_url=registry, executor_id=executor_id,
                        unique_parameter=scope, num_workers=1)
    started = time.monotonic()
    attempt = 0
    try:
        af.add(function_id)
        while True:
            attempt += 1
            try:
                af.call(function_id, dict(probe))
                elapsed = time.monotonic() - started
                print(f"  ok    {function_id}  ({scope})  serving after {elapsed:.0f}s, "
                      f"{attempt} call(s)")
                return True
            except Exception as e:                      # noqa: BLE001
                elapsed = time.monotonic() - started
                if elapsed > DEADLINE_S:
                    print(f"  FAIL  {function_id}  ({scope})  still not serving after "
                          f"{elapsed:.0f}s: {type(e).__name__}: {str(e)[:200]}",
                          file=sys.stderr)
                    return False
                print(f"        {function_id}: not serving yet ({elapsed:.0f}s) -- "
                      f"{type(e).__name__}")
                time.sleep(RETRY_S)
    finally:
        try:
            # Only this client's workers stop. The deployment stays up -- that is the
            # entire point of having warmed it.
            af.shutdown()
        except Exception:                               # noqa: BLE001
            pass


def main():
    registry = os.environ.get("FUNCTION_REGISTRY_URL")
    if not registry:
        print("FUNCTION_REGISTRY_URL is not set (see .env)", file=sys.stderr)
        return 1
    executor_id = os.environ.get("FUNCTION_EXECUTOR_ID") or "executor-001"

    print("=" * 58)
    print("Warming stateful function deployments")
    print(f"Registry: {registry}   executor: {executor_id}")
    print("=" * 58)

    warmed = targets()
    failed = 0
    for function_id, scope, probe in warmed:
        if not warm(function_id, scope, probe, registry, executor_id):
            failed += 1

    print()
    if failed:
        print(f"{failed} of {len(warmed)} deployments are not serving. Running a round "
              f"now will repeat the cold-start failures.", file=sys.stderr)
        return 1
    print(f"All {len(warmed)} deployments are serving. Safe to run a round.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
