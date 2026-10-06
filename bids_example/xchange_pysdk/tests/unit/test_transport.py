import logging
import pytest
import requests
import requests_mock

from xchange_pysdk import (
    XchangeClient,
    XchangeAPIError,
    XchangeError,
    XchangeNetworkError,
)


# --- Construction: address normalisation and timing defaults ---

@pytest.mark.parametrize("supplied", ["http://mock-xchange:5000", "http://mock-xchange:5000/"])
def test_trailing_separator_normalised(supplied):
    assert XchangeClient(base_url=supplied).base_url == "http://mock-xchange:5000"


def test_default_address_is_the_exchange_documented_default():
    assert XchangeClient().base_url == "http://localhost:5000"


def test_documented_timing_defaults():
    c = XchangeClient()
    assert c.default_poll_interval == 5
    assert c.default_wait_budget == 300
    assert c.default_timeout == 30


def test_timing_defaults_are_settable_at_construction():
    c = XchangeClient(poll_interval=1, wait_budget=None, timeout=(10, 300))
    assert c.default_poll_interval == 1
    assert c.default_wait_budget is None
    assert c.default_timeout == (10, 300)


# --- Per-call overrides ---

def test_client_default_timeout_used_when_call_omits_it(client):
    with requests_mock.Mocker() as m:
        m.get("http://mock-xchange:5000/tasks/t1", json={"ok": True, "data": {}})
        client.get_task("t1")
        assert m.last_request.timeout == 30


def test_per_call_timeout_overrides_and_does_not_mutate_client(client):
    with requests_mock.Mocker() as m:
        m.get("http://mock-xchange:5000/tasks/t1", json={"ok": True, "data": {}})
        client.get_task("t1", timeout=7)
        assert m.last_request.timeout == 7
    assert client.default_timeout == 30


def test_connect_read_pair_accepted_as_timeout(client):
    with requests_mock.Mocker() as m:
        m.get("http://mock-xchange:5000/tasks/t1", json={"ok": True, "data": {}})
        client.get_task("t1", timeout=(10, 300))
        assert m.last_request.timeout == (10, 300)


def test_per_call_log_level_does_not_mutate_client(client):
    with requests_mock.Mocker() as m:
        m.get("http://mock-xchange:5000/tasks/t1", json={"ok": True, "data": {}})
        client.get_task("t1", log_level=logging.DEBUG)
    assert client.default_log_level == logging.WARNING


# --- Envelope handling ---

def test_envelope_returned_whole_not_unwrapped(client):
    with requests_mock.Mocker() as m:
        m.get("http://mock-xchange:5000/tasks/t1", json={"ok": True, "data": {"task_id": "t1"}})
        resp = client.get_task("t1")
    assert resp == {"ok": True, "data": {"task_id": "t1"}}


# --- Error mapping ---

def test_api_error_carries_status_and_payload(client):
    with requests_mock.Mocker() as m:
        m.get(
            "http://mock-xchange:5000/tasks/t1",
            json={"ok": False, "error": "Task not found"},
            status_code=404,
        )
        with pytest.raises(XchangeAPIError) as exc:
            client.get_task("t1")
    assert "Task not found" in str(exc.value)
    assert exc.value.status_code == 404
    assert exc.value.payload.get("ok") is False


def test_network_failure_raises_network_error_chained(client):
    with requests_mock.Mocker() as m:
        m.get("http://mock-xchange:5000/tasks/t1", exc=requests.exceptions.ConnectTimeout)
        with pytest.raises(XchangeNetworkError) as exc:
            client.get_task("t1")
    assert exc.value.__cause__ is not None


def test_non_json_body_raises_api_error_not_decoding_error(client):
    with requests_mock.Mocker() as m:
        m.get("http://mock-xchange:5000/tasks/t1", text="<html>502 Bad Gateway</html>")
        with pytest.raises(XchangeAPIError):
            client.get_task("t1")


def test_bare_list_body_raises_api_error(client):
    with requests_mock.Mocker() as m:
        m.get("http://mock-xchange:5000/tasks/t1", json=[1, 2, 3])
        with pytest.raises(XchangeAPIError) as exc:
            client.get_task("t1")
    assert "Unexpected response structure" in str(exc.value)


def test_empty_body_raises_api_error(client):
    with requests_mock.Mocker() as m:
        m.get("http://mock-xchange:5000/tasks/t1", text="")
        with pytest.raises(XchangeAPIError):
            client.get_task("t1")


def test_error_status_with_non_json_body_still_raises_api_error(client):
    with requests_mock.Mocker() as m:
        m.get("http://mock-xchange:5000/tasks/t1", text="<html>500</html>", status_code=500)
        with pytest.raises(XchangeAPIError) as exc:
            client.get_task("t1")
    assert exc.value.status_code == 500
    assert exc.value.payload == {}


def test_every_sdk_error_derives_from_base():
    for cls in (XchangeNetworkError, XchangeAPIError):
        assert issubclass(cls, XchangeError)


# --- Diagnostics ---

def test_no_stream_handler_attached_by_default(client):
    logger = logging.getLogger("xchange_sdk")
    has_stream = any(
        isinstance(h, logging.StreamHandler) and not isinstance(h, logging.NullHandler)
        for h in logger.handlers
    )
    assert not has_stream, "SDK logger should not attach StreamHandler by default"
