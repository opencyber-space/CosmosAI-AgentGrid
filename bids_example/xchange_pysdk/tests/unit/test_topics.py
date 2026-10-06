"""Topic tagging and topic-based subject resolution.

A subject tags itself with `topics` at registration; a bidding-mode task can then pull
it into a bid job without naming it. The exchange matches with `{"topics": {"$in": [...]}}`,
so one overlapping tag is enough.

The documented resolution order (07-bidding-mode.md 7.2) is explicit list, then topics,
then every subject -- a priority chain, not a union. `test_explicit_ids_and_topics_are_both_sent`
pins the SDK's half of that contract: both keys reach the exchange, and which one wins
is the exchange's decision, not this client's.
"""
import requests_mock

BASE = "http://mock-xchange:5000"


# --- create_subject ---

def test_create_subject_sends_topics(client):
    with requests_mock.Mocker() as m:
        m.post(f"{BASE}/subjects", json={"ok": True, "data": {}}, status_code=201)
        client.create_subject(subject_id="a1", topics=["summarization", "nlp"])
        body = m.last_request.json()
    assert body["topics"] == ["summarization", "nlp"]


def test_create_subject_omits_topics_when_unset(client):
    """Omitted lets the exchange apply its own default of []."""
    with requests_mock.Mocker() as m:
        m.post(f"{BASE}/subjects", json={"ok": True, "data": {}}, status_code=201)
        client.create_subject(subject_id="a1", subject_capabilities={"gpu": True})
        body = m.last_request.json()
    assert "topics" not in body


def test_create_subject_sends_explicit_empty_topics(client):
    """An explicit [] is a deliberate 'tagged with nothing', distinct from omitting."""
    with requests_mock.Mocker() as m:
        m.post(f"{BASE}/subjects", json={"ok": True, "data": {}}, status_code=201)
        client.create_subject(subject_id="a1", topics=[])
        body = m.last_request.json()
    assert body["topics"] == []


def test_create_subject_topics_alongside_the_other_fields(client):
    with requests_mock.Mocker() as m:
        m.post(f"{BASE}/subjects", json={"ok": True, "data": {}}, status_code=201)
        client.create_subject(
            subject_id="agent-summarizer-01",
            subject_metadata={"owner": "team-nlp"},
            task_evaluation_function="accepts-if-capacity:1.0-stable",
            subject_capabilities={"max_doc_tokens": 50000},
            topics=["summarization", "nlp"],
        )
        body = m.last_request.json()
    assert body == {
        "subject_id": "agent-summarizer-01",
        "subject_metadata": {"owner": "team-nlp"},
        "task_evaluation_function": "accepts-if-capacity:1.0-stable",
        "subject_capabilities": {"max_doc_tokens": 50000},
        "topics": ["summarization", "nlp"],
    }


# --- submit_bidding_task ---

def test_bidding_task_sends_topics_under_task_assignment(client):
    with requests_mock.Mocker() as m:
        m.post(f"{BASE}/tasks", json={"ok": True, "data": {"task_id": "t1"}}, status_code=201)
        client.submit_bidding_task(
            task_data={"rfp_url": "http://minio/rfp.pdf"},
            bid_job_evaluator_id="va-bid-eval:1.0-stable",
            topics=["videoanalytics_bidding"],
        )
        body = m.last_request.json()
    assignment = body["task_metadata"]["task_assignment"]
    assert assignment["topics"] == ["videoanalytics_bidding"]
    assert assignment["bid_job_evaluator_id"] == "va-bid-eval:1.0-stable"


def test_bidding_task_omits_topics_when_unset(client):
    """Omitting both topics and subject_ids means 'every subject in the exchange'."""
    with requests_mock.Mocker() as m:
        m.post(f"{BASE}/tasks", json={"ok": True, "data": {}}, status_code=201)
        client.submit_bidding_task(
            task_data={"x": 1},
            bid_job_evaluator_id="va-bid-eval:1.0-stable",
        )
        assignment = m.last_request.json()["task_metadata"]["task_assignment"]
    assert "topics" not in assignment
    assert "bid_job_subject_ids" not in assignment


def test_explicit_ids_and_topics_are_both_sent(client):
    """The SDK forwards both; the exchange decides which wins.

    As documented today the explicit list short-circuits and the topic query never
    runs, so a caller wanting both must check the bid job's resolved subject ids. The
    client's job is only to transmit what it was given -- silently dropping one here
    would hide the exchange-side behaviour the caller needs to see.
    """
    with requests_mock.Mocker() as m:
        m.post(f"{BASE}/tasks", json={"ok": True, "data": {}}, status_code=201)
        client.submit_bidding_task(
            task_data={"x": 1},
            bid_job_evaluator_id="va-bid-eval:1.0-stable",
            bid_job_subject_ids=["a-bid-manager", "b-bid-manager", "c-bid-manager"],
            topics=["videoanalytics_bidding"],
        )
        assignment = m.last_request.json()["task_metadata"]["task_assignment"]
    assert assignment["bid_job_subject_ids"] == ["a-bid-manager", "b-bid-manager", "c-bid-manager"]
    assert assignment["topics"] == ["videoanalytics_bidding"]


def test_bidding_task_topics_survive_caller_supplied_metadata(client):
    """_with_assignment copies the caller's metadata and owns task_assignment."""
    caller_metadata = {"priority": "high"}
    with requests_mock.Mocker() as m:
        m.post(f"{BASE}/tasks", json={"ok": True, "data": {}}, status_code=201)
        client.submit_bidding_task(
            task_data={"x": 1},
            bid_job_evaluator_id="va-bid-eval:1.0-stable",
            topics=["videoanalytics_bidding"],
            task_metadata=caller_metadata,
        )
        metadata = m.last_request.json()["task_metadata"]
    assert metadata["priority"] == "high"
    assert metadata["task_assignment"]["topics"] == ["videoanalytics_bidding"]
    assert caller_metadata == {"priority": "high"}, "caller's dict must not be mutated"


# --- finding tagged subjects ---

def test_query_subjects_by_topic(client):
    """The same filter bidding mode itself uses to resolve a topic (03-apis.md 3.6)."""
    with requests_mock.Mocker() as m:
        m.post(
            f"{BASE}/subjects/query",
            json={"ok": True, "data": [
                {"subject_id": "ultravideotech-bid-manager"},
                {"subject_id": "videoproctech-bid-manager"},
            ]},
        )
        resp = client.query_subjects({"topics": {"$in": ["videoanalytics_bidding"]}})
        body = m.last_request.json()
    assert body == {"topics": {"$in": ["videoanalytics_bidding"]}}
    assert [s["subject_id"] for s in resp["data"]] == [
        "ultravideotech-bid-manager",
        "videoproctech-bid-manager",
    ]
