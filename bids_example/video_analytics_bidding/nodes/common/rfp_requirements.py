"""The RFP's requirement list, fetched from the function that owns it.

Every company used to extract its own list from the same tender, which meant every
company was scored out of a different denominator -- 0/16 for one bidder and 1/70 for
another on the same RFP (bid job 170a2315). `met / total` was not a score, because no
two bidders sat the same exam.

`va-rfp-requirements` now owns the list: it reads a given RFP url once, caches the
result against that url, and serves the identical list to everyone. This module is the
agent side of that call. The five AI Compliance Agents all use the same
`DEPLOYMENT_SCOPE`, so they reach one deployment and therefore one cache -- a per-company
scope would give each company its own process, its own cache and its own list, which is
the bug again with extra steps.

The model travels with the call. The function holds no credentials: each agent passes
its own block on `parameters.tool_model`, the same way the metrics demo passes
`tool_model` to `test-generator`.
"""
import logging
import time

from . import function_publisher

log = logging.getLogger(__name__)

FUNCTION_ID = "va-rfp-requirements:1.0-stable"


# A freshly created deployment reports live before the app inside it is serving: the
# SDK's ping loop breaks on the registry's `success`, and the call that follows cannot
# connect. Falling back on that first refusal is what put 37 and 26 on two bids whose
# shared list had 42 (bid job 9db948a0), so a connection failure is retried rather than
# treated as an answer. warmup.sh exists to make this path unnecessary; this is what
# happens when it was not run.
CALL_ATTEMPTS = 5
CALL_BACKOFF = 6.0      # seconds, doubling: about 90s of patience in total


def _call_with_retry(af, rfp_url, parameters):
    last = None
    for attempt in range(1, CALL_ATTEMPTS + 1):
        try:
            return af.call(FUNCTION_ID, {"rfp_url": rfp_url}, parameters=parameters)
        except Exception as e:                                          # noqa: BLE001
            last = e
            if not _looks_like_a_cold_start(e) or attempt == CALL_ATTEMPTS:
                raise
            delay = CALL_BACKOFF * (2 ** (attempt - 1))
            log.warning("rfp_requirements: %s not serving yet (attempt %d/%d: %s); "
                        "retrying in %.0fs", FUNCTION_ID, attempt, CALL_ATTEMPTS,
                        type(e).__name__, delay)
            time.sleep(delay)
    raise last


def _looks_like_a_cold_start(error):
    """A pod that is not up yet, as opposed to a function that answered with a refusal."""
    text = str(error).lower()
    return any(sign in text for sign in (
        "connecttimeout", "connection refused", "max retries exceeded",
        "failed to establish a new connection", "read timed out", "502", "503", "504"))


def tool_model_for(subject, model_name=None):
    """The caller's own model block, as a plain dict.

    `llm_parameters` carries the api_key, which is what lets the function build a dspy
    LM without holding a key of its own.
    """
    integrations = getattr(subject, "integrations", None)
    models = getattr(integrations, "models", None)
    if models is None and isinstance(integrations, dict):
        models = integrations.get("models")
    models = models or []

    chosen = None
    for model in models:
        block_id = (getattr(model, "llm_block_id", None)
                    or (model.get("llm_block_id") if isinstance(model, dict) else None))
        if model_name and block_id != model_name:
            continue
        chosen = model
        break
    if chosen is None and models:
        chosen = models[0]      # the agent asked for a model this subject does not list
    if chosen is None:
        return {}

    if not isinstance(chosen, dict):
        chosen = chosen.to_dict() if hasattr(chosen, "to_dict") else {
            "llm_block_id": getattr(chosen, "llm_block_id", ""),
            "llm_parameters": dict(getattr(chosen, "llm_parameters", {}) or {}),
        }
    return chosen


def fetch(rfp_url, subject, model_name=None, agent_functions=None,
          registry_url=None, executor_id=None):
    """The canonical requirements for this RFP.

    Returns the function's own shape -- usecases, total_licenses, requirements,
    benchmarked_usecases -- plus `requirements_source`, which says whether the list came
    from the shared function or from a local fallback. Raises only if the caller has no
    usable answer at all; a caller that wants to fall back should catch and do so, and
    record the source, because a silent fallback is how five different denominators
    creep back in unnoticed.
    """
    if not rfp_url:
        raise ValueError("no rfp_url supplied")

    af, owned = agent_functions, False
    if af is None:
        from agents_functions import AgentFunctions
        registry = registry_url or function_publisher.registry_url_from_env()
        if not registry:
            raise RuntimeError("FUNCTION_REGISTRY_URL is unset; cannot reach va-rfp-requirements")
        af = AgentFunctions(
            functions_registry_url=registry,
            executor_id=executor_id or function_publisher.executor_id_from_env(),
            # Shared with every other company on purpose: one deployment, one cache.
            unique_parameter=function_publisher.DEPLOYMENT_SCOPE,
            num_workers=2,
        )
        owned = True

    try:
        af.add(FUNCTION_ID)      # mandatory: call() raises without it
        answer = _call_with_retry(
            af, rfp_url, {"tool_model": tool_model_for(subject, model_name)})
    finally:
        if owned:
            try:
                # The deployment stays up -- it holds the cache the next company needs.
                # Only this client's worker threads are stopped.
                af.shutdown()
            except Exception:       # noqa: BLE001
                log.warning("rfp_requirements: AgentFunctions shutdown failed")

    asked = _unwrap(answer)
    status = asked.get("status")
    if status and status != "ok":
        raise RuntimeError(f"va-rfp-requirements returned {status}: {asked.get('error')}")
    if not isinstance(asked.get("requirements"), list):
        raise RuntimeError(f"va-rfp-requirements returned no requirement list: {asked!r}")

    asked["requirements_source"] = "shared_function"
    log.info("rfp_requirements: %d requirements for %s (cached=%s)",
             len(asked["requirements"]), rfp_url, asked.get("cached"))
    return asked


def _unwrap(answer):
    """The registry wraps a function result; how deeply depends on the call path."""
    for _ in range(4):
        if not isinstance(answer, dict):
            return {}
        if "requirements" in answer or "status" in answer:
            return answer
        nested = None
        for key in ("data", "result", "output", "body"):
            candidate = answer.get(key)
            if isinstance(candidate, dict):
                nested = candidate
                break
        if nested is None:
            return answer
        answer = nested
    return answer if isinstance(answer, dict) else {}
