class AIOSv1PolicyRule:
    def __init__(self, rule_id, settings, parameters):
        self.rule_id = rule_id
        self.settings = settings
        self.parameters = parameters

    def _as_number(self, value):
        # Coerce a bid's compute field to a number. Accepts the agreed tier strings
        # ("low" | "moderate" | "high"), plain numerics, and anything else an LLM
        # might emit. Never raises: one unscoreable bid must not fail the whole job.
        tiers = {"low": 500, "moderate": 1500, "high": 3000}
        unknown = 1500
        if isinstance(value, bool):
            return float(unknown)
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            text = value.strip().lower()
            if text in tiers:
                return float(tiers[text])
            try:
                return float(text)
            except ValueError:
                for name in ("low", "moderate", "high"):
                    if name in text:
                        return float(tiers[name])
                return float(unknown)
        return float(unknown)

    def eval(self, parameters, input_data, context):
        bids = input_data.get("bids", [])
        if not bids:
            return {"status": "no_valid_bids"}

        best_score = float('inf')
        winner = None

        for bid in bids:
            bid_data = bid.get("bid_data", {}) or {}

            # A manager that declined the job is not a candidate to win it.
            if str(bid_data.get("bid_status", "")).lower() == "declined":
                continue
            if bid_data.get("bid_rejected",False):
                continue

            tokens = self._as_number(bid_data.get("total_estimated_tokens", 0))
            compute = self._as_number(bid_data.get("required_compute", 0))

            score = (tokens * 0.5) + (compute * 0.5)

            if score < best_score:
                best_score = score
                winner = bid

        if not winner:
            return {"status": "no_valid_bids"}

        return {
            "winner_subject_id": winner.get("bid_subject_id"),
            "status": "resolved",
            "result_data": {
                "reason": "lowest combined score",
                "score": best_score
            }
        }
