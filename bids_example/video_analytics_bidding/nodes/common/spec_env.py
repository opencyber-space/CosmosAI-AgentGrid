"""Settings an agent takes from its own registered spec.

The agent image carries only a handful of keys from the repo `.env`, and the deployer
injects a handful more onto the pod. Everything else an agent needs -- where MinIO is,
which function registry to publish to, where HIS lives -- comes from its subject spec,
under `persona.config.parameters`. `spec/register.sh` expands the `${...}` placeholders
from `.env` at registration time, so a setting changes with a re-register and a pod
restart rather than a rebuild.

`apply()` copies those parameters into the process environment, because the helpers that
need them (`minio_store`, `function_publisher`, `his_logger`) already read exactly these
names. Nothing here overwrites a variable the pod was started with: `setdefault` means
an explicit deployment-time value still wins, and the spec only fills what is absent.

Reporting a missing setting is deliberately left to whoever needs it. An agent that
cannot reach MinIO must still answer -- its Bid Manager has to submit a declining bid, or
the round never resolves -- so failing here would trade a recoverable decline for a
permanently stalled bid job.
"""
import logging
import os

log = logging.getLogger(__name__)

# MINIO_CONFIG's keys, and the environment names the MinIO helpers already look for.
# MINIO_URL / MINIO_EXTERNAL_URL land on the VA_* overrides, which `minio_store` checks
# before falling back to INTERNAL_IP/EXTERNAL_IP and the port variables.
MINIO_KEYS = {
    "MINIO_URL": "VA_MINIO_URL",
    "MINIO_EXTERNAL_URL": "VA_MINIO_EXTERNAL_URL",
    "MINIO_ACCESS_KEY": "MINIO_ACCESS_KEY",
    "MINIO_SECRET_KEY": "MINIO_SECRET_KEY",
    "MINIO_INTERNAL_PORT": "MINIO_INTERNAL_PORT",
    "MINIO_EXTERNAL_PORT": "MINIO_EXTERNAL_PORT",
}

# Scalar parameters that carry the same name in the environment.
PASSTHROUGH = (
    "FUNCTION_REGISTRY_URL",
    "FUNCTION_UPLOAD_URL",
    "FUNCTION_EXECUTOR_ID",
    # OpenArcade, as the Bid Managers read it. The spec value is filled from the repo
    # .env's OPENARCADE_BIDDING_URL at registration, but the agent only knows the new name.
    "ORCADE_URL",
    "ORCADE_POLL_SECONDS",
    "EXCHANGE_BASE_URL",
    # Which va-uc-* version the compliance agents ask the registry for. Here rather than
    # compiled into the image so that bumping it -- which the policies system's artifact
    # caching forces every time an endpoint's code changes -- is a redeploy rather than
    # five image builds. It must match functions/build_endpoints.py, which stamps the
    # packages, and both default to the same value in endpoint_names.py.
    "VA_ENDPOINT_VERSION",
    "VA_ENDPOINT_RELEASE_TAG",
)


def parameters(subject):
    """`persona.config.parameters` for this subject, or {} when the spec has none."""
    persona = getattr(subject, "persona", None)
    if persona is None:
        return {}
    config = getattr(persona, "config", None)
    if config is None and isinstance(persona, dict):
        config = persona.get("config")
    if not isinstance(config, dict):
        return {}
    params = config.get("parameters")
    return params if isinstance(params, dict) else {}


def _set(name, value):
    """Set one variable, unless the pod was started with it."""
    if value is None:
        return False
    text = str(value).strip()
    if not text or text.startswith("${"):
        # An unexpanded placeholder means `register.sh` ran without that key in `.env`.
        # Writing it through would produce a literal "${INTERNAL_IP}:9000" address and a
        # connection error that says nothing about the cause.
        return False
    before = os.environ.get(name)
    os.environ.setdefault(name, text)
    return before is None


def apply(subject):
    """Copy this subject's spec parameters into the environment. Returns the names set."""
    params = parameters(subject)
    if not params:
        log.warning("no persona.config.parameters on this subject; "
                    "MinIO and the function registry will fall back to the environment")
        return []

    applied = []

    minio = params.get("MINIO_CONFIG")
    if isinstance(minio, dict):
        for key, env_name in MINIO_KEYS.items():
            if _set(env_name, minio.get(key)):
                applied.append(env_name)
    else:
        log.warning("spec has no MINIO_CONFIG; the RFP and the workbooks will be unreachable")

    for name in PASSTHROUGH:
        if _set(name, params.get(name)):
            applied.append(name)

    his = params.get("HIS_CONFIG")
    if isinstance(his, dict) and _set("HIS_BASE_URL", his.get("HIS_BASE_URL")):
        applied.append("HIS_BASE_URL")

    log.info("spec settings applied: %s", ", ".join(sorted(applied)) or "none")
    return applied
