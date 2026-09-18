import json
from function.code.function import AIOSv1PolicyRule

def test_evaluator():
    rule = AIOSv1PolicyRule("bids-evaluator:1.0-stable", {}, {})
    input_data = {
        "bid_job": {"bid_job_id": "test_job"},
        "bids": [
            {
                "bid_subject_id": "agent-1",
                "bid_data": {"total_estimated_tokens": 100, "required_compute": 50}
            },
            {
                "bid_subject_id": "agent-2",
                "bid_data": {"total_estimated_tokens": 80, "required_compute": 40}
            },
            {
                "bid_subject_id": "agent-3",
                "bid_data": {"total_estimated_tokens": 120, "required_compute": 60}
            }
        ]
    }
    
    # agent-1 score = 50 + 25 = 75
    # agent-2 score = 40 + 20 = 60
    # agent-3 score = 60 + 30 = 90
    # Winner should be agent-2

    result = rule.eval({}, input_data, {})
    assert result.get("winner_subject_id") == "agent-2", f"Expected agent-2, got {result.get('winner_subject_id')}"
    print("Evaluator test passed:", json.dumps(result))

if __name__ == "__main__":
    test_evaluator()
