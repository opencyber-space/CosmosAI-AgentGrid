"""Scoring maths for the video-analytics bidding round.

The evaluator scores surviving bids on four dimensions -- budget, hardware footprint,
use-case compliance and live endpoint accuracy -- each on a comparable 100-point basis,
and the highest total wins.

Budget and hardware are scored by *standing within the field*, not against fixed
thresholds, so a bid is only ever cheap or heavy relative to the others in the round.
Declined and pre-qualification-rejected bids are filtered out before any of this runs,
so the field is the survivors alone.

This module is vendored into the evaluator's function package at build time -- the
function registry runs `function/code/` as an isolated package with no access to the
repo tree -- so it must stay dependency-free (standard library only).
"""
import logging
import math

log = logging.getLogger(__name__)

SIZING_FIELDS = ("cpu_cores", "ram_gb", "disk_gb", "gpu_count")

# Accelerators dominate, storage matters least. Overridable per round via
# bid_job_metadata.evaluation.weights; these sum to 1.0 so a weighted sizing score
# lands in [0, 100] like the other three dimensions.
DEFAULT_SIZING_WEIGHTS = {"cpu": 0.2, "ram": 0.2, "disk": 0.1, "gpu": 0.5}

_WEIGHT_KEY_FOR_FIELD = {
    "cpu_cores": "cpu",
    "ram_gb": "ram",
    "disk_gb": "disk",
    "gpu_count": "gpu",
}


def get_percentile_ranks(data):
    """Percentile rank of every value, by the round's agreed formula.

    ``((count strictly less than x) + 0.5) / n * 100``, rounded to 1 decimal.

    Ties share a rank, since the count is of values *strictly* less:

        >>> get_percentile_ranks([10, 3, 8, 5, 8])
        [90.0, 10.0, 50.0, 30.0, 50.0]

    An empty field returns an empty list rather than raising -- the evaluator can be
    handed a round where nothing survived filtering.
    """
    n = len(data)
    if n == 0:
        return []
    ranks = []
    for x in data:
        less_than_x = sum(1 for item in data if item < x)
        ranks.append(round(((less_than_x + 0.5) / n) * 100, 1))
    return ranks


def relative_scores(values):
    """Field-relative 100-point scores where a LOWER input scores HIGHER.

    Used for budget and for each hardware dimension: the cheapest bid and the leanest
    footprint win their dimension. With two survivors the ranks are [25, 75] and so the
    scores are [75, 25] -- a small field degenerates to coarse steps, but the ordering
    still holds and the weighted sum still decides the round.
    """
    return [round(100.0 - rank, 1) for rank in get_percentile_ranks(values)]


def _as_number(value, fallback=None):
    """Coerce a bid field to a float, or return `fallback` if it cannot be.

    Bids are assembled by LLM-driven agents, so a field can arrive as "4.85 Cr", None or
    a bare int. Never raises: one unscoreable field must not fail the whole round.
    """
    if isinstance(value, bool):
        return fallback
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip().replace(",", ""))
        except ValueError:
            return fallback
    return fallback


def budget_scores(bids):
    """Budget dimension (a), keyed by subject id.

    A bid whose `total_budget` cannot be read as a number is treated as the most
    expensive in the field, so it sinks to the bottom of this dimension rather than
    raising or being silently dropped.
    """
    if not bids:
        return {}
    raw = [_as_number(b.get("bid_data", {}).get("total_budget")) for b in bids]
    known = [v for v in raw if v is not None]
    worst = max(known) if known else 0.0
    values = [v if v is not None else worst + 1.0 for v in raw]
    scores = relative_scores(values)
    return {b.get("bid_subject_id"): s for b, s in zip(bids, scores)}


def weighted_sizing_scores(bids, weights=None):
    """Hardware dimension (b), keyed by subject id.

    Each of cpu/ram/disk/gpu is ranked independently within the field, then combined:

        100 * sum(weight[d] * (100 - percentile[d]) / 100)

    A missing or unreadable dimension is treated as the heaviest in the field, for the
    same reason as budget: it lowers that company's score without derailing the round.
    """
    if not bids:
        return {}
    weights = dict(DEFAULT_SIZING_WEIGHTS) if weights is None else dict(weights)

    per_field_scores = {}
    for field in SIZING_FIELDS:
        raw = [
            _as_number((b.get("bid_data", {}).get("sizing") or {}).get(field))
            for b in bids
        ]
        known = [v for v in raw if v is not None]
        worst = max(known) if known else 0.0
        values = [v if v is not None else worst + 1.0 for v in raw]
        per_field_scores[field] = relative_scores(values)

    totals = {}
    for i, bid in enumerate(bids):
        combined = 0.0
        for field in SIZING_FIELDS:
            weight = weights.get(_WEIGHT_KEY_FOR_FIELD[field], 0.0)
            combined += weight * per_field_scores[field][i]
        totals[bid.get("bid_subject_id")] = round(combined, 1)
    return totals


def compliance_score(bid_data):
    """Compliance dimension (c): `met / total * 100`.

    Returns 0.0 when the report is missing or `total` is zero -- a company that never
    reported a compliance summary earns nothing here rather than dividing by zero.
    """
    compliance = bid_data.get("compliance") or {}
    met = _as_number(compliance.get("met"), 0.0) or 0.0
    total = _as_number(compliance.get("total"), 0.0) or 0.0
    if total <= 0:
        log.info("compliance total is missing or zero; scoring 0 for this bid")
        return 0.0
    return round(min(met / total, 1.0) * 100.0, 1)


def endpoint_score(correct, total):
    """Endpoint dimension (d): `correct / total * 100`.

    `total` is the number of calls actually attempted. A failed call counts as a wrong
    answer -- it is included in `total` and excluded from `correct` -- so an unreachable
    endpoint lowers the score instead of aborting evaluation. A company that reported no
    endpoints at all has `total == 0` and scores 0.
    """
    if not total:
        return 0.0
    return round((correct / total) * 100.0, 1)


def total_score(budget, sizing, compliance, endpoint):
    """Sum of the four dimensions. Maximum 400."""
    return round(budget + sizing + compliance + endpoint, 1)


def pick_winner(scored):
    """The winning subject id from `{subject_id: {"total": float, ...}}`.

    Ties break deterministically -- lowest `total_budget` first, then lexicographically
    lowest subject id -- so the same bids always yield the same winner. Never delegated
    to `bid_job_tie_id`, which OpenArcade accepts but does not invoke.

    Returns `(subject_id, tie_break_reason)`; `tie_break_reason` is None when the top
    total was unique, and `(None, None)` when there is nothing to pick from.
    """
    if not scored:
        return None, None

    best_total = max(entry["total"] for entry in scored.values())
    tied = [sid for sid, entry in scored.items() if entry["total"] == best_total]
    if len(tied) == 1:
        return tied[0], None

    by_budget = sorted(
        tied,
        key=lambda sid: (
            _as_number(scored[sid].get("total_budget"), math.inf),
            sid,
        ),
    )
    winner = by_budget[0]
    budgets = {sid: scored[sid].get("total_budget") for sid in tied}
    if len(set(budgets.values())) > 1:
        reason = f"tied on {best_total}; resolved by lowest total_budget"
    else:
        reason = f"tied on {best_total} and on budget; resolved by lowest subject id"
    log.info("%s among %s -> %s", reason, tied, winner)
    return winner, reason


def normalize_va_bid(bid_data):
    """Settle a bid's numeric fields in code before it is submitted.

    The agents that assemble a bid are LLM-driven, and the evaluator reads
    `total_budget` and the four `sizing` values as numbers. A model that emits
    "4.85 Cr" or "640 cores" would make the bid unscoreable, so the coercion happens
    here rather than being left to prompt discipline -- the same reason
    `bid_utils.normalize_bid` exists for the bids_processing example.

    Values that cannot be coerced are left untouched and logged, so the problem shows
    up in the bid record rather than being masked by a plausible default.
    """
    bid = dict(bid_data or {})

    budget = _as_number(bid.get("total_budget"))
    if budget is None:
        if bid.get("bid_status") != "declined":
            log.info("Bid total_budget %r is not numeric; leaving as-is", bid.get("total_budget"))
    else:
        bid["total_budget"] = budget

    sizing = dict(bid.get("sizing") or {})
    for field in SIZING_FIELDS:
        if field not in sizing:
            continue
        value = _as_number(sizing[field])
        if value is None:
            log.info("Bid sizing.%s %r is not numeric; leaving as-is", field, sizing[field])
        else:
            sizing[field] = value
    if sizing:
        bid["sizing"] = sizing

    endpoints = bid.get("live_endpoints")
    if isinstance(endpoints, list):
        bid["live_endpoints"] = [e for e in endpoints if isinstance(e, dict) and e.get("verified")]

    return bid
