import pytest
import requests_mock
from openarcade_bidding_pysdk.client import OpenarcadeClient
from openarcade_bidding_pysdk.exceptions import OpenarcadeNetworkError

@pytest.fixture
def client():
    return OpenarcadeClient(base_url="http://mock-arcade:5000")

def test_create_bid_job(client):
    with requests_mock.Mocker() as m:
        m.post("http://mock-arcade:5000/bid-jobs", json={"ok": True, "data": {"bid_job_id": "123"}})
        resp = client.create_bid_job(
            bid_job_name={"en": "test"},
            bid_job_description={},
            bid_job_evaluator_id="eval-1",
            bid_job_creator_id="creator-1",
            bid_job_subject_ids=["agent-1"]
        )
        assert resp["ok"] is True
        assert resp["data"]["bid_job_id"] == "123"

def test_get_bid_job(client):
    with requests_mock.Mocker() as m:
        m.get("http://mock-arcade:5000/bid-jobs/123", json={"ok": True, "data": {"bid_job_id": "123"}})
        resp = client.get_bid_job("123")
        assert resp["data"]["bid_job_id"] == "123"

def test_update_bid_job(client):
    with requests_mock.Mocker() as m:
        m.patch("http://mock-arcade:5000/bid-jobs/123", json={"ok": True})
        resp = client.update_bid_job("123", {"bid_job_metadata": {"x": 1}})
        assert resp["ok"] is True

def test_delete_bid_job(client):
    with requests_mock.Mocker() as m:
        m.delete("http://mock-arcade:5000/bid-jobs/123", json={"ok": True})
        resp = client.delete_bid_job("123")
        assert resp["ok"] is True

def test_query_bid_jobs(client):
    with requests_mock.Mocker() as m:
        m.post("http://mock-arcade:5000/bid-jobs/query", json={"ok": True, "data": []})
        resp = client.query_bid_jobs({"bid_job_creator_id": "creator-1"})
        assert resp["data"] == []

def test_submit_bid(client):
    with requests_mock.Mocker() as m:
        m.post("http://mock-arcade:5000/bid-jobs/123/bids", json={"ok": True, "data": {"bid_id": "b1"}})
        resp = client.submit_bid("123", "agent-1", {"price": 10})
        assert resp["ok"] is True

def test_get_job_bids(client):
    with requests_mock.Mocker() as m:
        m.get("http://mock-arcade:5000/bid-jobs/123/bids", json={"ok": True, "data": []})
        resp = client.get_job_bids("123")
        assert resp["ok"] is True

def test_get_bid(client):
    with requests_mock.Mocker() as m:
        m.get("http://mock-arcade:5000/bids/b1", json={"ok": True, "data": {"bid_id": "b1"}})
        resp = client.get_bid("b1")
        assert resp["ok"] is True

def test_update_bid(client):
    with requests_mock.Mocker() as m:
        m.patch("http://mock-arcade:5000/bids/b1", json={"ok": True})
        resp = client.update_bid("b1", {"bid_data": {"price": 5}})
        assert resp["ok"] is True

def test_delete_bid(client):
    with requests_mock.Mocker() as m:
        m.delete("http://mock-arcade:5000/bids/b1", json={"ok": True})
        resp = client.delete_bid("b1")
        assert resp["ok"] is True

def test_query_bids(client):
    with requests_mock.Mocker() as m:
        m.post("http://mock-arcade:5000/bids/query", json={"ok": True, "data": []})
        resp = client.query_bids({"bid_subject_id": "agent-1"})
        assert resp["ok"] is True

def test_get_job_task_results(client):
    with requests_mock.Mocker() as m:
        m.get("http://mock-arcade:5000/bid-jobs/123/task-results", json={"ok": True, "data": []})
        resp = client.get_job_task_results("123")
        assert resp["ok"] is True

def test_query_task_results(client):
    with requests_mock.Mocker() as m:
        m.post("http://mock-arcade:5000/bid-task-results/query", json={"ok": True, "data": []})
        resp = client.query_task_results({"bid_subject_id": "agent-1"})
        assert resp["ok"] is True

def test_no_stream_handler(client):
    # Ensure there are no StreamHandlers attached to the SDK logger
    # Only NullHandler should be present by default.
    import logging
    logger = logging.getLogger("openarcade_sdk")
    has_stream_handler = any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.NullHandler) for h in logger.handlers)
    assert not has_stream_handler, "SDK logger should not attach StreamHandler by default"

def test_api_error_raised_on_400(client):
    from openarcade_bidding_pysdk.exceptions import OpenarcadeAPIError
    with requests_mock.Mocker() as m:
        m.post("http://mock-arcade:5000/bid-jobs/123/bids", json={"ok": False, "error": "Bad Request"}, status_code=400)
        with pytest.raises(OpenarcadeAPIError) as exc_info:
            client.submit_bid("123", "agent-1", {})
        
        assert "Bad Request" in str(exc_info.value)
        assert exc_info.value.status_code == 400
        assert exc_info.value.payload.get("ok") is False
