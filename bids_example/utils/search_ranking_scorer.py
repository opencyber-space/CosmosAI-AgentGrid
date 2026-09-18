import math
from typing import List, Dict, Any, Tuple

class AgentRanker:
    """
    Implements the mathematical scoring logic for ranking agents.
    - Calculates a feedback_score from raw user feedback data.
    - Calculates a final_score by combining the feedback_score and a domain_match_score with given weights.
    """

    def __init__(self, feedback_weights: dict[str, float] = None, final_score_weights: dict[str, float] = None):
        # Feedback component weights
        self.feedback_weights = feedback_weights or {
            "problem": 0.45,
            "rating": 0.25,
            "thumbs": 0.20,
            "sent": 0.10,
        }
        # Final score weights
        self.final_score_weights = final_score_weights or {
            "domain": 0.20,
            "feedback": 0.80,
        }

    def _clamp(self, value: float, min_val: float = 0.0, max_val: float = 1.0) -> float:
        return max(min_val, min(value, max_val))

    def _normalize_problem_solved(self, data: Dict[str, Any]) -> float:
        perc = data.get("problem_solved_percentage", 0)
        return self._clamp(perc / 100.0)

    def _normalize_rating_stars(self, data: Dict[str, Any]) -> float:
        stars = data.get("rating_stars", 0)
        return self._clamp(stars / 5.0)

    def _normalize_thumbs(self, data: Dict[str, Any]) -> float:
        up = data.get("thumbs_up", 0)
        down = data.get("thumbs_down", 0)
        if up + down == 0:
            return 0.5  # Default for no votes
        delta = up - down
        denom = up + down
        ratio = delta / denom
        return (ratio + 1) / 2.0

    def _normalize_sentiment(self, data: Dict[str, Any]) -> float:
        sentiment = str(data.get("sentiment", "neutral")).lower()
        if sentiment == "positive":
            return 1.0
        if sentiment == "negative":
            return 0.0
        return 0.5  # neutral

    def _calculate_feedback_score(self, feedback_data: Dict[str, Any]) -> Dict[str, float]:
        norms = {
            "problem": self._normalize_problem_solved(feedback_data),
            "rating": self._normalize_rating_stars(feedback_data),
            "thumbs": self._normalize_thumbs(feedback_data),
            "sent": self._normalize_sentiment(feedback_data),
        }

        feedback_score = (
            self.feedback_weights["problem"] * norms["problem"] +
            self.feedback_weights["rating"] * norms["rating"] +
            self.feedback_weights["thumbs"] * norms["thumbs"] +
            self.feedback_weights["sent"] * norms["sent"]
        )
        
        return {"feedback_score": feedback_score, "norms": norms}

    def calculate_final_score(self, feedback_data: Dict[str, Any], domain_match_score: float) -> Dict[str, Any]:
        """
        Calculates the final weighted score for a single agent.
        
        Args:
            feedback_data: Raw dictionary of user feedback metrics.
            domain_match_score: A score from 0.0 to 1.0 indicating domain relevance (e.g., from an LLM).
        """
        feedback_result = self._calculate_feedback_score(feedback_data)
        feedback_score = feedback_result["feedback_score"]
        
        # Combine domain match and feedback score using the final weights
        final_score = (
            self.final_score_weights["domain"] * self._clamp(domain_match_score) +
            self.final_score_weights["feedback"] * feedback_score
        )
        
        final_score = round(self._clamp(final_score), 3)

        return {
            "score": final_score,
            "details": {
                "feedback_score": round(feedback_score, 3),
                "domain_match_score": round(self._clamp(domain_match_score), 3),
                "norms": {k: round(v, 3) for k, v in feedback_result["norms"].items()}
            }
        }
