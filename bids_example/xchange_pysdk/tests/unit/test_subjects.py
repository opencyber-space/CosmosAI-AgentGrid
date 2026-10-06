import pytest
import requests_mock

from xchange_pysdk import XchangeAPIError

BASE = "http://mock-xchange:5000"


# --- create ---

def test_create_subject_posts_supplied_fields(client):
    with requests_mock.Mocker() as m:
        m.post(f"{BASE}/subjects", json={"ok": True, "data": {"subject_id": "a1"}}, status_code=201)
        resp = client.create_subject(
            subject_id="a1",
            subject_metadata={"owner": "team-nlp"},
            task_evaluation_function="accepts-if-capacity:1.0",
            subject_capabilities={"max_doc_tokens": 50000},
        )
        body = m.last_request.json()
    assert m.last_request.path == "/subjects"
    assert resp["data"]["subject_id"] == "a1"
    assert body == {
        "subject_id": "a1",
        "subject_metadata": {"owner": "team-nlp"},
        "task_evaluation_function": "accepts-if-capacity:1.0",
        "subject_capabilities": {"max_doc_tokens": 50000},
    }


def test_create_subject_omits_every_unset_field(client):
    """Omitted fields let the exchange apply uuid4(), {}, "" and {}."""
    with requests_mock.Mocker() as m:
        m.post(f"{BASE}/subjects", json={"ok": True, "data": {}}, status_code=201)
        client.create_subject()
        body = m.last_request.json()
    assert body == {}


def test_create_subject_without_evaluation_function_is_accepted(client):
    """A subject with no acceptance function never joins open-mode evaluation. Legal."""
    with requests_mock.Mocker() as m:
        m.post(f"{BASE}/subjects", json={"ok": True, "data": {}}, status_code=201)
        client.create_subject(subject_id="a1", subject_capabilities={"gpu": True})
        body = m.last_request.json()
    assert "task_evaluation_function" not in body


def test_create_subject_sends_explicit_empty_evaluation_function(client):
    with requests_mock.Mocker() as m:
        m.post(f"{BASE}/subjects", json={"ok": True, "data": {}}, status_code=201)
        client.create_subject(subject_id="a1", task_evaluation_function="")
        body = m.last_request.json()
    assert body["task_evaluation_function"] == ""


# --- read ---

def test_get_subject(client):
    with requests_mock.Mocker() as m:
        m.get(f"{BASE}/subjects/a1", json={"ok": True, "data": {"subject_id": "a1"}})
        resp = client.get_subject("a1")
    assert m.last_request.path == "/subjects/a1"
    assert resp["data"]["subject_id"] == "a1"


# --- update ---

def test_update_subject_patches_and_returns_refreshed_record(client):
    updates = {"subject_capabilities": {"max_doc_tokens": 80000}}
    with requests_mock.Mocker() as m:
        m.patch(f"{BASE}/subjects/a1", json={"ok": True, "data": {"subject_id": "a1", **updates}})
        resp = client.update_subject("a1", updates)
        body = m.last_request.json()
    assert m.last_request.method == "PATCH"
    assert m.last_request.path == "/subjects/a1"
    assert body == updates
    assert resp["data"]["subject_capabilities"]["max_doc_tokens"] == 80000


# --- delete ---

def test_delete_subject(client):
    with requests_mock.Mocker() as m:
        m.delete(f"{BASE}/subjects/a1", json={"ok": True, "data": {"deleted": True}})
        resp = client.delete_subject("a1")
    assert m.last_request.method == "DELETE"
    assert resp["data"]["deleted"] is True


# --- not found ---

@pytest.mark.parametrize("verb,method", [("get", "get_subject"), ("delete", "delete_subject")])
def test_missing_subject_raises_404(client, verb, method):
    with requests_mock.Mocker() as m:
        getattr(m, verb)(
            f"{BASE}/subjects/nope",
            json={"ok": False, "error": "Subject not found"},
            status_code=404,
        )
        with pytest.raises(XchangeAPIError) as exc:
            getattr(client, method)("nope")
    assert exc.value.status_code == 404


def test_missing_subject_update_raises_404(client):
    with requests_mock.Mocker() as m:
        m.patch(
            f"{BASE}/subjects/nope",
            json={"ok": False, "error": "Subject not found"},
            status_code=404,
        )
        with pytest.raises(XchangeAPIError) as exc:
            client.update_subject("nope", {"subject_metadata": {}})
    assert exc.value.status_code == 404


# --- query ---

def test_query_subjects_forwards_filter_verbatim(client):
    filter_query = {"task_evaluation_function": {"$ne": ""}}
    with requests_mock.Mocker() as m:
        m.post(f"{BASE}/subjects/query", json={"ok": True, "data": []})
        client.query_subjects(filter_query)
        body = m.last_request.json()
    assert m.last_request.path == "/subjects/query"
    assert body == filter_query
