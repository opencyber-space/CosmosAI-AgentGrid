import pytest
import requests_mock

from xchange_pysdk import XchangeAPIError, XchangeClient, XchangeTimeoutError

BASE = "http://mock-xchange:5000"
OUTPUT_URL = f"{BASE}/tasks/t1/output"


@pytest.fixture
def fake_clock(monkeypatch):
    """
    Replace time.sleep and time.monotonic so the suite asserts real poll behaviour in
    no elapsed time. This is what keeps a 300s default budget compatible with an
    offline suite that must run in milliseconds.
    """
    import xchange_pysdk.client as mod

    state = {"now": 0.0, "sleeps": []}

    def fake_sleep(seconds):
        state["sleeps"].append(seconds)
        state["now"] += seconds

    monkeypatch.setattr(mod.time, "sleep", fake_sleep)
    monkeypatch.setattr(mod.time, "monotonic", lambda: state["now"])
    return state


def status(value):
    return {"ok": True, "data": {"task_assignment_status": value, "task_output": {}}}


# --- Settling ---

def test_returns_once_task_settles(client, fake_clock):
    with requests_mock.Mocker() as m:
        m.get(OUTPUT_URL, [
            {"json": status("pending")},
            {"json": status("assigned")},
            {"json": status("completed")},
        ])
        resp = client.wait_for_task("t1")
    assert resp["data"]["task_assignment_status"] == "completed"
    assert len(fake_clock["sleeps"]) == 2


def test_returns_immediately_if_already_terminal(client, fake_clock):
    with requests_mock.Mocker() as m:
        m.get(OUTPUT_URL, json=status("completed"))
        client.wait_for_task("t1")
    assert fake_clock["sleeps"] == []


@pytest.mark.parametrize("terminal", ["completed", "failed", "rejected"])
def test_every_terminal_state_returns_rather_than_raises(client, fake_clock, terminal):
    """failed and rejected are ordinary outcomes, not SDK errors."""
    with requests_mock.Mocker() as m:
        m.get(OUTPUT_URL, json=status(terminal))
        resp = client.wait_for_task("t1")
    assert resp["data"]["task_assignment_status"] == terminal


def test_rejected_carries_its_explanation_through(client, fake_clock):
    body = {"ok": True, "data": {
        "task_assignment_status": "rejected",
        "task_output": {"error": "no subject accepted the task"},
    }}
    with requests_mock.Mocker() as m:
        m.get(OUTPUT_URL, json=body)
        resp = client.wait_for_task("t1")
    assert resp["data"]["task_output"]["error"] == "no subject accepted the task"


def test_unrecognised_status_keeps_polling(client, fake_clock):
    with requests_mock.Mocker() as m:
        m.get(OUTPUT_URL, [
            {"json": status("some_future_state")},
            {"json": status("completed")},
        ])
        resp = client.wait_for_task("t1")
    assert resp["data"]["task_assignment_status"] == "completed"
    assert len(fake_clock["sleeps"]) == 1


# --- Budget exhaustion ---

def test_budget_exhaustion_raises_timeout_with_context(client, fake_clock):
    with requests_mock.Mocker() as m:
        m.get(OUTPUT_URL, json=status("bidding"))
        with pytest.raises(XchangeTimeoutError) as exc:
            client.wait_for_task("t1", wait_budget=20)
    assert exc.value.task_id == "t1"
    assert exc.value.last_status == "bidding"
    assert sum(fake_clock["sleeps"]) <= 20


def test_client_default_budget_used_when_omitted(client, fake_clock):
    with requests_mock.Mocker() as m:
        m.get(OUTPUT_URL, json=status("bidding"))
        with pytest.raises(XchangeTimeoutError):
            client.wait_for_task("t1")
    assert sum(fake_clock["sleeps"]) <= 300
    assert sum(fake_clock["sleeps"]) > 200


def test_explicit_none_budget_waits_past_the_default(client, fake_clock):
    """An explicit None opts into the exchange's own unbounded behaviour."""
    responses = [{"json": status("bidding")} for _ in range(200)]
    responses.append({"json": status("completed")})
    with requests_mock.Mocker() as m:
        m.get(OUTPUT_URL, responses)
        resp = client.wait_for_task("t1", wait_budget=None)
    assert resp["data"]["task_assignment_status"] == "completed"
    assert sum(fake_clock["sleeps"]) > 300, "should have polled past the default budget"


def test_unbounded_client_default_also_waits_past_300(fake_clock):
    c = XchangeClient(base_url=BASE, wait_budget=None)
    responses = [{"json": status("bidding")} for _ in range(200)]
    responses.append({"json": status("completed")})
    with requests_mock.Mocker() as m:
        m.get(OUTPUT_URL, responses)
        c.wait_for_task("t1")
    assert sum(fake_clock["sleeps"]) > 300


# --- Transient failure tolerance ---

def test_transient_500_is_survived(client, fake_clock):
    with requests_mock.Mocker() as m:
        m.get(OUTPUT_URL, [
            {"json": {"ok": False, "error": "boom"}, "status_code": 500},
            {"json": status("completed")},
        ])
        resp = client.wait_for_task("t1")
    assert resp["data"]["task_assignment_status"] == "completed"


def test_transient_network_failure_is_survived(client, fake_clock):
    import requests as _requests
    with requests_mock.Mocker() as m:
        m.get(OUTPUT_URL, [
            {"exc": _requests.exceptions.ConnectTimeout},
            {"json": status("completed")},
        ])
        resp = client.wait_for_task("t1")
    assert resp["data"]["task_assignment_status"] == "completed"


def test_404_is_reraised_immediately_not_polled_through(client, fake_clock):
    """A missing task is not transient; polling it for the full budget misdiagnoses it."""
    with requests_mock.Mocker() as m:
        m.get(OUTPUT_URL, json={"ok": False, "error": "not found"}, status_code=404)
        with pytest.raises(XchangeAPIError) as exc:
            client.wait_for_task("t1")
    assert exc.value.status_code == 404
    assert fake_clock["sleeps"] == [], "should not have slept at all"


# --- T027: sleep durations come from the resolved parameters ---

def test_sleep_duration_comes_from_client_default(fake_clock):
    c = XchangeClient(base_url=BASE, poll_interval=1)
    with requests_mock.Mocker() as m:
        m.get(OUTPUT_URL, [{"json": status("pending")}, {"json": status("completed")}])
        c.wait_for_task("t1")
    assert fake_clock["sleeps"] == [1]


def test_per_call_poll_interval_overrides_client_default(fake_clock):
    c = XchangeClient(base_url=BASE, poll_interval=5)
    with requests_mock.Mocker() as m:
        m.get(OUTPUT_URL, [{"json": status("pending")}, {"json": status("completed")}])
        c.wait_for_task("t1", poll_interval=0.5)
    assert fake_clock["sleeps"] == [0.5]
    assert c.default_poll_interval == 5, "client default must not be mutated"


def test_default_poll_interval_is_five_seconds(client, fake_clock):
    with requests_mock.Mocker() as m:
        m.get(OUTPUT_URL, [{"json": status("pending")}, {"json": status("completed")}])
        client.wait_for_task("t1")
    assert fake_clock["sleeps"] == [5]


def test_per_call_request_timeout_reaches_the_poll_requests(client, fake_clock):
    with requests_mock.Mocker() as m:
        m.get(OUTPUT_URL, json=status("completed"))
        client.wait_for_task("t1", timeout=(10, 300))
        assert m.last_request.timeout == (10, 300)
