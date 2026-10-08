"""Reporting what an agent received and produced to the Human Intervention System.

Every agent in this example posts two records per task -- what came in, and what went
out -- against its own `SUBJECT_ID`. The dashboard reads them back per subject, so the
round can be watched live, agent by agent, while it runs.

This is observability, not control flow. HIS being unreachable must never change what an
agent decides or stop it returning a report: a Bid Manager that fails to log and
therefore fails to bid would stall the whole round, which is a far worse outcome than a
missing dashboard entry. Every call here swallows its own errors.

The envelope keeps `text`, `source_id`, `destination_id`, `team` and `timestamp` so the
records read the same way as `bids_processing`, and adds the structured fields this
example's dashboard groups by.
"""
import json
import logging
import os
import time

log = logging.getLogger(__name__)

# Full agent reports can be large -- a compliance verdict carries a point per RFP
# requirement. HIS is a live view, not an archive, so payloads are bounded here. The
# authoritative copy of the chain rides on the bid itself as `agent_trace`.
MAX_LIST_ITEMS = 10
MAX_STRING_CHARS = 1500


def build_client(subject):
    """A HisClient from the agent's own spec, or None if HIS is not configured.

    Returns None rather than raising: an agent with no HIS configured is a normal
    deployment, not a broken one.
    """
    try:
        from agents_sdk.core.his import HisClient
    except Exception as e:                      # pragma: no cover - import-time only
        log.warning("HIS client unavailable (%s); agent reporting is off", e)
        return None

    config = {}
    try:
        persona_config = getattr(getattr(subject, "persona", None), "config", None) or {}
        config = (persona_config.get("parameters") or {}).get("HIS_CONFIG") or {}
    except Exception:
        config = {}

    base_url = config.get("HIS_BASE_URL") or os.environ.get("HIS_BASE_URL")
    if not base_url:
        log.info("no HIS_BASE_URL configured; agent reporting is off")
        return None

    try:
        return HisClient(
            base_url=base_url,
            poll_interval=float(config.get("HIS_POLL_INTERVAL", 1.0)),
            max_wait=int(config.get("HIS_MAX_WAIT", 120)),
        )
    except Exception as e:
        log.warning("could not build the HIS client (%s); agent reporting is off", e)
        return None


def summarise(value, depth=0):
    """A bounded, JSON-serializable view of an agent payload."""
    if depth > 3:
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


def report(client, *, subject_id, company, role, event, payload,
           destination_id="USER_OR_NEXT", stage=None, bid_job_id=None, note=None):
    """Post one record. Never raises, never blocks a decision.

    `event` is one of INCOMING_TASK, OUTGOING_RESULT, STAGE_DISPATCH, STAGE_RESULT.
    """
    if client is None:
        return
    try:
        body = summarise(payload)
        message = {
            # Kept for parity with the bids_processing dashboard, which renders `text`.
            "text": json.dumps({"event": event, "stage": stage, "payload": body},
                               default=str)[:4000],
            "source_id": subject_id,
            "destination_id": destination_id,
            "team": company,
            "timestamp": time.time(),
            # Structured fields this example's dashboard groups by.
            "event": event,
            "company": company,
            "role": role,
            "stage": stage,
            "bid_job_id": bid_job_id,
            "note": note,
            "payload": body,
        }
        client.submit(input_data=message)
    except Exception as e:
        # Observability must never cost a bid.
        log.debug("HIS report failed (%s: %s); continuing", event, e)
