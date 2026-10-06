import pytest
import requests_mock

BASE = "http://mock-xchange:5000"


@pytest.fixture
def posted(client):
    """Submit via a helper and hand back the outgoing request body."""
    def _run(fn, *args, **kwargs):
        with requests_mock.Mocker() as m:
            m.post(f"{BASE}/tasks", json={"ok": True, "data": {"task_id": "t1"}}, status_code=201)
            fn(*args, **kwargs)
            return m.last_request.json()
    return _run


# --- direct ---

def test_direct_builds_subject_id_block(client, posted):
    body = posted(client.submit_direct_task, task_data={"x": 1}, subject_id="agent-01")
    assert body["task_assignment_type"] == "direct"
    assert body["task_metadata"]["task_assignment"] == {"subject_id": "agent-01"}


# --- function ---

def test_function_builds_function_id_block(client, posted):
    body = posted(client.submit_function_task, task_data={"x": 1}, function_id="pick-biggest:1.0")
    assert body["task_assignment_type"] == "function"
    assert body["task_metadata"]["task_assignment"] == {"function_id": "pick-biggest:1.0"}


def test_function_omits_parameters_when_unset(client, posted):
    body = posted(client.submit_function_task, task_data={"x": 1}, function_id="f:1.0")
    assert "parameters" not in body["task_metadata"]["task_assignment"]


def test_function_includes_parameters_when_supplied(client, posted):
    body = posted(
        client.submit_function_task,
        task_data={"x": 1},
        function_id="f:1.0",
        parameters={"threshold": 10},
    )
    assert body["task_metadata"]["task_assignment"]["parameters"] == {"threshold": 10}


# --- open ---

def test_open_sends_no_assignment_block_at_all(client, posted):
    """open mode ignores task_assignment entirely; sending one would be noise."""
    body = posted(client.submit_open_task, task_data={"x": 1})
    assert body["task_assignment_type"] == "open"
    assert "task_metadata" not in body


def test_open_with_caller_metadata_still_sends_no_assignment_block(client, posted):
    body = posted(client.submit_open_task, task_data={"x": 1}, task_metadata={"owner": "team"})
    assert body["task_metadata"] == {"owner": "team"}
    assert "task_assignment" not in body["task_metadata"]


# --- bidding ---

def test_bidding_with_only_evaluator_sends_only_evaluator(client, posted):
    body = posted(
        client.submit_bidding_task,
        task_data={"x": 1},
        bid_job_evaluator_id="lowest-cost:1.0",
    )
    assert body["task_assignment_type"] == "bidding"
    assert body["task_metadata"]["task_assignment"] == {"bid_job_evaluator_id": "lowest-cost:1.0"}


def test_bidding_omits_subject_ids_so_exchange_defaults_to_all_subjects(client, posted):
    """Sending [] would open a bid job with ZERO subjects instead of every subject."""
    body = posted(
        client.submit_bidding_task,
        task_data={"x": 1},
        bid_job_evaluator_id="e:1.0",
    )
    assert "bid_job_subject_ids" not in body["task_metadata"]["task_assignment"]


def test_bidding_sends_explicit_empty_subject_list_when_caller_insists(client, posted):
    """An explicit [] is the caller's choice and must not be silently dropped."""
    body = posted(
        client.submit_bidding_task,
        task_data={"x": 1},
        bid_job_evaluator_id="e:1.0",
        bid_job_subject_ids=[],
    )
    assert body["task_metadata"]["task_assignment"]["bid_job_subject_ids"] == []


def test_bidding_forwards_every_optional_field_when_supplied(client, posted):
    body = posted(
        client.submit_bidding_task,
        task_data={"x": 1},
        bid_job_evaluator_id="e:1.0",
        bid_job_subject_ids=["a", "b"],
        bid_job_pqt_id="pqt:1.0",
        bid_job_tie_id="tie:1.0",
        bid_job_metadata={"m": 1},
        bid_job_description={"d": 1},
        bid_job_name={"en": "job"},
        bid_job_creator_id="creator-1",
    )
    assert body["task_metadata"]["task_assignment"] == {
        "bid_job_evaluator_id": "e:1.0",
        "bid_job_subject_ids": ["a", "b"],
        "bid_job_pqt_id": "pqt:1.0",
        "bid_job_tie_id": "tie:1.0",
        "bid_job_metadata": {"m": 1},
        "bid_job_description": {"d": 1},
        "bid_job_name": {"en": "job"},
        "bid_job_creator_id": "creator-1",
    }


# --- Metadata merge rule (applies to every helper) ---

def test_caller_metadata_survives_alongside_assignment_block(client, posted):
    body = posted(
        client.submit_direct_task,
        task_data={"x": 1},
        subject_id="agent-01",
        task_metadata={"owner": "team-nlp", "trace_id": "abc"},
    )
    assert body["task_metadata"]["owner"] == "team-nlp"
    assert body["task_metadata"]["trace_id"] == "abc"
    assert body["task_metadata"]["task_assignment"] == {"subject_id": "agent-01"}


def test_helper_assignment_block_wins_over_caller_supplied_one(client, posted):
    body = posted(
        client.submit_direct_task,
        task_data={"x": 1},
        subject_id="agent-01",
        task_metadata={"task_assignment": {"subject_id": "WRONG"}},
    )
    assert body["task_metadata"]["task_assignment"] == {"subject_id": "agent-01"}


def test_callers_metadata_dict_is_never_mutated(client):
    """Example scripts reuse one metadata dict across submissions; leaking would break them."""
    shared = {"owner": "team-nlp"}
    with requests_mock.Mocker() as m:
        m.post(f"{BASE}/tasks", json={"ok": True, "data": {}}, status_code=201)
        client.submit_direct_task(task_data={"x": 1}, subject_id="agent-01", task_metadata=shared)
        first = m.last_request.json()["task_metadata"]
        client.submit_direct_task(task_data={"x": 2}, subject_id="agent-02", task_metadata=shared)
        second = m.last_request.json()["task_metadata"]
    assert shared == {"owner": "team-nlp"}, "caller's dict was mutated"
    assert first["task_assignment"] == {"subject_id": "agent-01"}
    assert second["task_assignment"] == {"subject_id": "agent-02"}


def test_task_id_passes_through_every_helper(client, posted):
    for fn, kwargs in [
        (client.submit_direct_task, {"subject_id": "a"}),
        (client.submit_function_task, {"function_id": "f:1.0"}),
        (client.submit_open_task, {}),
        (client.submit_bidding_task, {"bid_job_evaluator_id": "e:1.0"}),
    ]:
        body = posted(fn, task_data={"x": 1}, task_id="fixed-id", **kwargs)
        assert body["task_id"] == "fixed-id"
