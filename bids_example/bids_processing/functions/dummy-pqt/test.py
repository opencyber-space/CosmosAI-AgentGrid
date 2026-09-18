import json
from function.code.function import AIOSv1PolicyRule

def test_dummy_pqt():
    rule = AIOSv1PolicyRule("dummy-pqt:1.0-stable", {}, {})
    input_data = {
        "bid_job": {"bid_job_id": "test_job"},
        "bid": {"bid_id": "test_bid"}
    }
    result = rule.eval({}, input_data, {})
    assert result.get("accepted") is True
    print("Dummy PQT test passed:", json.dumps(result))

if __name__ == "__main__":
    test_dummy_pqt()
