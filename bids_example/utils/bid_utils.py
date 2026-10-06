"""Bid fields a program can pin down, so a model's wording cannot distort a bid.

The bid aggregation signature asks for `proposed_timeline`, `required_compute` and
`manager_id`, but a model sometimes omits a field or renames itself. The evaluator and the
dashboard read those fields, so they are settled here instead of being left to the model.
`total_estimated_tokens` is deliberately left as the model reported it.
"""
import logging

log = logging.getLogger(__name__)

COMPUTE_TIERS = ("low", "moderate", "high")
TIMELINES = ("fast", "medium", "slow")


def _clean(value):
    return value.strip().lower() if isinstance(value, str) else ""


def highest_compute(assessments):
    """Highest compute tier any sub-agent reported in its assessment, or None."""
    best = -1
    for response in (assessments or {}).values():
        output = response.get("job_output") if isinstance(response, dict) and isinstance(response.get("job_output"), dict) else response
        tier = _clean((output or {}).get("compute_required")) if isinstance(output, dict) else ""
        if tier in COMPUTE_TIERS:
            best = max(best, COMPUTE_TIERS.index(tier))
    return COMPUTE_TIERS[best] if best >= 0 else None


def normalize_bid(bid_data, assessments, subject_id=None):
    """Return the bid with its enum fields and manager_id settled in code.

    - proposed_timeline: kept when it is fast|medium|slow, otherwise "medium".
    - required_compute: kept when it is low|moderate|high, otherwise the highest tier the
      sub-agents reported (falling back to "moderate" when they reported none).
    - manager_id: always this agent's own subject_id.
    """
    bid = dict(bid_data or {})

    timeline = _clean(bid.get("proposed_timeline"))
    if timeline not in TIMELINES:
        log.info(f"Bid proposed_timeline {bid.get('proposed_timeline')!r} is missing or invalid; using 'medium'")
        timeline = "medium"
    bid["proposed_timeline"] = timeline

    compute = _clean(bid.get("required_compute"))
    if compute not in COMPUTE_TIERS:
        compute = highest_compute(assessments) or "moderate"
        log.info(f"Bid required_compute {bid.get('required_compute')!r} is missing or invalid; using '{compute}' from the sub-agent assessments")
    bid["required_compute"] = compute

    if subject_id:
        bid["manager_id"] = subject_id
    return bid
