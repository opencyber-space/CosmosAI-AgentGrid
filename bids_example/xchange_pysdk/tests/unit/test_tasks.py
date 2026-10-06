import pytest
import requests_mock

from xchange_pysdk import XchangeAPIError, XchangeClient


BASE = "http://mock-xchange:5000"


# --- submit_task ---

def test_submit_task_posts_required_fields(client):
    with requests_mock.Mocker() as m:
        m.post(f"{BASE}/tasks", json={"ok": True, "data": {"task_id": "t1"}}, status_code=201)
        resp = client.submit_task(
            task_assignment_type="direct",
            task_data={"instruction": "summarize"},
        )
        body = m.last_request.json()
    assert resp["data"]["task_id"] == "t1"
    assert body["task_assignment_type"] == "direct"
    assert body["task_data"] == {"instruction": "summarize"}


def test_submit_task_omits_unset_optional_fields(client):
    """Unset optionals must be absent so the exchange applies its own defaults."""
    with requests_mock.Mocker() as m:
        m.post(f"{BASE}/tasks", json={"ok": True, "data": {}}, status_code=201)
        client.submit_task(task_assignment_type="open", task_data={"x": 1})
        body = m.last_request.json()
    assert "task_id" not in body
    assert "task_assignment_status" not in body
    assert "task_metadata" not in body
    assert set(body) == {"task_assignment_type", "task_data"}


def test_submit_task_includes_optional_fields_when_supplied(client):
    with requests_mock.Mocker() as m:
        m.post(f"{BASE}/tasks", json={"ok": True, "data": {}}, status_code=201)
        client.submit_task(
            task_assignment_type="direct",
            task_data={"x": 1},
            task_id="my-id",
            task_assignment_status="pending",
            task_metadata={"owner": "team-nlp"},
        )
        body = m.last_request.json()
    assert body["task_id"] == "my-id"
    assert body["task_assignment_status"] == "pending"
    assert body["task_metadata"] == {"owner": "team-nlp"}


def test_submit_task_falsy_task_data_still_sent(client):
    """task_data is required; an empty dict is a legitimate payload, not an omission."""
    with requests_mock.Mocker() as m:
        m.post(f"{BASE}/tasks", json={"ok": True, "data": {}}, status_code=201)
        client.submit_task(task_assignment_type="open", task_data={})
        body = m.last_request.json()
    assert body["task_data"] == {}


def test_submit_task_400_raises_api_error(client):
    with requests_mock.Mocker() as m:
        m.post(
            f"{BASE}/tasks",
            json={"ok": False, "error": "task_data is required"},
            status_code=400,
        )
        with pytest.raises(XchangeAPIError) as exc:
            client.submit_task(task_assignment_type="direct", task_data=None)
    assert exc.value.status_code == 400


# --- get_task / get_task_output ---

def test_get_task_hits_full_record_endpoint(client):
    with requests_mock.Mocker() as m:
        m.get(f"{BASE}/tasks/t1", json={"ok": True, "data": {"task_id": "t1"}})
        resp = client.get_task("t1")
    assert m.last_request.path == "/tasks/t1"
    assert resp["data"]["task_id"] == "t1"


def test_get_task_output_hits_output_endpoint(client):
    payload = {"task_assignment_status": "completed", "task_output": {"summary": "..."}}
    with requests_mock.Mocker() as m:
        m.get(f"{BASE}/tasks/t1/output", json={"ok": True, "data": payload})
        resp = client.get_task_output("t1")
    assert m.last_request.path == "/tasks/t1/output"
    assert resp["data"]["task_assignment_status"] == "completed"


def test_get_task_preserves_upstream_typo_in_creation_time(client):
    """taski_creation_time is an upstream typo; the SDK must never silently rename it."""
    record = {"task_id": "t1", "taski_creation_time": "2026-09-17T10:15:32.481203"}
    with requests_mock.Mocker() as m:
        m.get(f"{BASE}/tasks/t1", json={"ok": True, "data": record})
        resp = client.get_task("t1")
    assert "taski_creation_time" in resp["data"]
    assert "task_creation_time" not in resp["data"]


def test_get_task_404_raises_api_error(client):
    with requests_mock.Mocker() as m:
        m.get(f"{BASE}/tasks/nope", json={"ok": False, "error": "not found"}, status_code=404)
        with pytest.raises(XchangeAPIError) as exc:
            client.get_task("nope")
    assert exc.value.status_code == 404


# --- query_tasks ---

def test_query_tasks_forwards_filter_verbatim(client):
    filter_query = {
        "task_assignment_type": "open",
        "task_assignment_status": {"$ne": "completed"},
        "taski_creation_time": {"$exists": True},
    }
    with requests_mock.Mocker() as m:
        m.post(f"{BASE}/tasks/query", json={"ok": True, "data": []})
        client.query_tasks(filter_query)
        body = m.last_request.json()
    assert m.last_request.path == "/tasks/query"
    assert body == filter_query


def test_query_tasks_does_not_mutate_callers_filter(client):
    filter_query = {"task_assignment_status": "bidding"}
    original = dict(filter_query)
    with requests_mock.Mocker() as m:
        m.post(f"{BASE}/tasks/query", json={"ok": True, "data": []})
        client.query_tasks(filter_query)
    assert filter_query == original


# --- The exchange offers no task mutation; the SDK must not invent it ---

@pytest.mark.parametrize("forbidden", ["update_task", "delete_task", "patch_task"])
def test_no_task_mutation_methods_exposed(forbidden):
    assert not hasattr(XchangeClient, forbidden)
