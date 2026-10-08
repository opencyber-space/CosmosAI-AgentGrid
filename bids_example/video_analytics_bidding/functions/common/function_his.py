"""HIS reporting from inside a registry function.

The 30 agents each post what they received and what they produced to HIS, which is what
the dashboard's Companies and Timeline tabs read. The two functions OpenArcade calls --
pre-qualification and the evaluator -- were the blind spot: their reasoning existed only
in a pod log nobody opens, so the Evaluation tab could show the scores but never how they
were arrived at, and a pre-qualification rejection was a one-line `reason` on a declining
bid with no record of what was actually checked.

This is the agents' `nodes/common/his_logger.py` rewritten for a function. It cannot
import that module or `agents_sdk`: the registry runs `function/code/` as an isolated
tree, so this posts to the HIS REST API directly. `functions/build.sh` vendors it into
both functions, the same way it vendors `va_bid_utils.py`.

Two rules carry over from the agent side, and matter more here:

  * It never raises. A function that failed to log and therefore failed to answer would
    stall the round permanently -- OpenArcade waits on the evaluator with no timeout, and
    a pre-qualification error rejects the bid.
  * It never blocks for long. Pre-qualification runs inside the bid-submission path and
    the evaluator inside OpenArcade's 60-second budget, so the timeout here is seconds,
    not the default.
"""
import json
import logging
import os
import time

import requests

log = logging.getLogger(__name__)

# Bounds, so one enormous bid cannot push a multi-megabyte record into HIS. Same limits
# the agents use, for records that read the same in the dashboard.
MAX_STRING_CHARS = 1200
MAX_LIST_ITEMS = 25

# Short on purpose: see the module docstring. A HIS that is slow or down costs the round
# nothing beyond this.
TIMEOUT_S = 3.0


def base_url(settings=None, bid_job=None):
    """Where HIS is, from whichever of the three routes carries it.

    `function_settings` is the intended one -- functions/build.sh expands ${HIS_BASE_URL}
    into the manifest at package time, so the value travels with the function and no
    environment needs preparing. The bid job is a fallback for a deployment whose
    settings predate this, and the environment is the last resort.
    """
    try:
        his = (settings or {}).get("HIS_CONFIG")
        url = his.get("HIS_BASE_URL") if isinstance(his, dict) else None
        if not url and isinstance(bid_job, dict):
            evaluation = (bid_job.get("bid_job_metadata") or {}).get("evaluation") or {}
            his_config = evaluation.get("his_config")
            url = ((his_config.get("HIS_BASE_URL") if isinstance(his_config, dict) else None)
                   or evaluation.get("his_base_url"))
        url = url or os.environ.get("HIS_BASE_URL")
    except Exception as e:                                          # noqa: BLE001
        # Same contract as report(): a misshapen setting turns reporting off, it does not
        # take the function down. This runs before any try inside report(), so it needs
        # its own -- a HIS_CONFIG that arrived as a string would otherwise reject every
        # bid the pre-qualification function saw.
        log.warning("could not read the HIS base url (%s); reporting is off", e)
        return None
    if not url or "${" in str(url):
        # An unexpanded placeholder means the package was built without .env; reporting
        # off is the right outcome, not a request to a literal "${HIS_BASE_URL}".
        return None
    return str(url).rstrip("/")


# A function's payload nests one level deeper than an agent's: payload -> checks ->
# one check -> the list of certifications it compared. At the agents' depth of 3 that
# list came out as ["...", "..."], in the single column a reader consults to see why a
# company was rejected. Width is still bounded by MAX_LIST_ITEMS and MAX_STRING_CHARS,
# so this costs a little depth, not an unbounded record.
MAX_DEPTH = 5


def summarise(value, depth=0):
    """A bounded, JSON-serializable view of a payload."""
    if depth > MAX_DEPTH:
        return "..."
    if isinstance(value, dict):
        return {k: summarise(v, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        kept = [summarise(v, depth + 1) for v in value[:MAX_LIST_ITEMS]]
        if len(value) > MAX_LIST_ITEMS:
            kept.append(f"... {len(value) - MAX_LIST_ITEMS} more")
        return kept
    if isinstance(value, str) and len(value) > MAX_STRING_CHARS:
        return value[:MAX_STRING_CHARS] + f" ... [{len(value)} chars]"
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:MAX_STRING_CHARS]


def report(url, subject_id, role, event, payload, *, company=None, stage=None,
           bid_job_id=None, destination_id="openarcade", note=None):
    """Post one record. Never raises, never blocks a decision.

    `event` is one of INCOMING_TASK, OUTGOING_RESULT -- the same vocabulary the agents
    use, so the dashboard renders a function's record with the same icons and the same
    input/output pairing as an agent's.
    """
    if not url:
        return False
    try:
        body = summarise(payload)
        message = {
            # Kept for parity with the agents' records, which the dashboard renders.
            "text": json.dumps({"event": event, "stage": stage, "payload": body},
                               default=str)[:4000],
            "source_id": subject_id,
            "destination_id": destination_id,
            "team": company or "evaluation",
            "timestamp": time.time(),
            "event": event,
            "company": company,
            "role": role,
            "stage": stage,
            "bid_job_id": bid_job_id,
            "note": note,
            "payload": body,
        }
        response = requests.post(
            f"{url}/subject-responses",
            json={"subject_id": subject_id, "input_data": message, "status": "pending"},
            timeout=TIMEOUT_S,
        )
        response.raise_for_status()
        return True
    except Exception as e:                                          # noqa: BLE001
        # Observability must never cost a round.
        log.warning("HIS report failed (%s: %s); continuing", event, e)
        return False
