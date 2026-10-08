"""Reaching the company's live use-case endpoints from inside the agent.

The RFP puts certain use cases under a live accuracy benchmark, and each company stands
up a callable endpoint for them. Those endpoints are no longer built or uploaded from
here. They are packaged per company by `functions/build_endpoints.py`, uploaded by
`upload.sh` and brought up by `warmup.sh`, all before the round starts.

That move was not cosmetic. Publishing from inside the agent put a registry upload *and*
a first-ever deployment creation inside the bidding window, where a container start plus
a pip install is measured against OpenArcade's 60-second evaluator budget -- the cold
start that broke bid job 9db948a0 -- and `warmup.sh` could not help, because the
functions did not exist until the round was already running. It also meant the answers
each endpoint gives had to be readable by the agent, which is what kept them in
config.yaml.

What the agent still does is the part worth demonstrating: it reads the RFP, decides
which of its declared endpoints that tender actually calls for, proves each one answers,
and puts those on its bid. An endpoint that does not answer is left off -- that costs
this company endpoint score; it does not fail the bid, because a stand-in failing to
deploy is not a reason to lose a tender.
"""
import logging
import os

from .endpoint_names import (MAX_FUNCTION_NAME, declared_endpoints,  # noqa: F401
                             function_id_for, function_name_for, slug)
from .minio_store import load_env

log = logging.getLogger(__name__)

# The registry runs a function on a named executor and 404s on one it does not have --
# "Executor not found", surfaced as a 502 from /function/call_as_job. The name is a
# property of the deployment, not of this example, so it comes from the spec and only
# falls back to the platform's conventional executor.
DEFAULT_EXECUTOR_ID = "executor-001"

# AgentFunctions composes a deployment name as "{function_name}-{unique_parameter}".
# warmup.sh creates the deployment and the evaluator reuses it, so both must pass this
# same value -- with anything per-agent or per-round in there they would address two
# different deployments and the reuse would silently not happen.
DEPLOYMENT_SCOPE = "va-live"

# Any name works: an image the endpoint has no packaged verdict for is answered with its
# default verdict rather than refused, and a boolean of either value proves the pod is
# serving, which is all verification is for.
PROBE_IMAGE = "probe.png"


def registry_url_from_env():
    return os.environ.get("FUNCTION_REGISTRY_URL")


def executor_id_from_env():
    return os.environ.get("FUNCTION_EXECUTOR_ID") or DEFAULT_EXECUTOR_ID


def verify(function_id, probe_image=PROBE_IMAGE, agent_functions=None, registry_url=None,
           executor_id=None):
    """One real round-trip through the registry, so a broken endpoint is caught here.

    The contract is that an endpoint is only reported once it has answered.
    """
    load_env()
    af = agent_functions
    owned = False
    if af is None:
        from agents_functions import AgentFunctions  # vendored into the agent image
        registry = registry_url or registry_url_from_env()
        if not registry:
            raise RuntimeError("FUNCTION_REGISTRY_URL must be set (see .env.template)")
        af = AgentFunctions(
            functions_registry_url=registry,
            executor_id=executor_id or executor_id_from_env(),
            unique_parameter=DEPLOYMENT_SCOPE,
        )
        owned = True

    try:
        af.add(function_id)                       # required before call(), which raises otherwise
        result = af.call(function_id, {"image_name": probe_image, "image_url": ""})
        ok = isinstance(result, dict) and isinstance(result.get("result"), bool)
        if not ok:
            log.warning("%s answered %r, which is not a boolean verdict", function_id, result)
        return ok, result
    finally:
        if owned:
            af.shutdown()                         # the worker pool will not exit on its own


def resolve_usecase_endpoints(company_slug, usecase_ids, declared, max_endpoints=2,
                              probe_image=PROBE_IMAGE, agent_functions=None):
    """Verify this company's endpoints for the use cases the RFP benchmarks.

    `usecase_ids` is what the RFP asks to see benchmarked; `declared` is what this
    company stands up (`live_endpoints.endpoints` in its config, which is what was built
    and uploaded). Only the intersection can be offered -- naming an endpoint that was
    never uploaded would have the evaluator call an id nobody registered and score this
    company 0 for it. If the RFP benchmarks nothing this company has, its own declared
    endpoints are offered instead, so the example still demonstrates live evaluation.

    Returns `(published, failures)` where `published` is the `live_endpoints` list that
    goes on the bid -- `{usecase, function_id, verified: True}` -- and `failures` records
    what went wrong for anything that did not make it, so the agent can say so in its
    report rather than silently reporting fewer endpoints.
    """
    published, failures = [], []

    declared = list(declared or [])
    wanted = [uc for uc in (usecase_ids or []) if uc in declared] or declared
    selected = wanted[:max_endpoints]
    if len(wanted) > max_endpoints:
        log.info("%s: %d candidate use cases; offering the first %d (configured cap)",
                 company_slug, len(wanted), max_endpoints)

    for usecase_id in selected:
        function_id = function_id_for(company_slug, usecase_id)
        try:
            ok, result = verify(function_id, probe_image, agent_functions=agent_functions)
            if ok:
                published.append({"usecase": usecase_id, "function_id": function_id,
                                  "verified": True})
                log.info("%s: %s verified", company_slug, function_id)
            else:
                failures.append({"usecase": usecase_id, "function_id": function_id,
                                 "error": f"verification returned {result!r}"})
        except Exception as e:
            # One endpoint failing must not stop the others, and must not fail the bid.
            # The usual cause is that upload.sh or warmup.sh was not run for this round,
            # which the message says plainly rather than leaving a bare connection error.
            log.warning("%s: endpoint %s did not answer: %s", company_slug, function_id, e)
            failures.append({"usecase": usecase_id, "function_id": function_id,
                             "error": f"{e} (was build.sh/upload.sh/warmup.sh run?)"})

    return published, failures
