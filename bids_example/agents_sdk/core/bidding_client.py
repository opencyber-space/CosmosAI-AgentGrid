"""
Python client for the Orcade bidding service.

Single-file, standalone: depends only on ``requests`` and the standard library,
so it can be copied into an agent without importing the server code.

Quick start::

    from bidding_client import (
        BiddingClient, BidSubmission, BidTagQuery, BidJob,
    )

    client = BiddingClient("http://localhost:5000")

    bid = client.submit_bid(BidSubmission(
        bid_job_id="8f14e45f-ceea-4a19-8f6e-8b5a9c1a9f10",
        bid_subject_id="agent-translator-01",
        bid_data={"price_usd": 120.0, "eta_hours": 6, "confidence": 0.92},
    ))

    job = client.get_bid_job(bid.bid_job_id)

    jobs = client.find_bid_jobs_by_tags(BidTagQuery(tags=["translation", "fr"]))

    class MyAgent:
        def on_bidding_task(self, bid_task_data: BidJob) -> None:
            ...  # decide whether to apply, then call client.submit_bid(...)

    poller = client.poll_bid_tasks(
        BidTagQuery(tags=["translation"]),
        MyAgent(),
        interval_seconds=10,
    )
    ...
    poller.stop()
"""

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Protocol
from urllib.parse import quote

import requests

__all__ = [
    "BidJob",
    "Bid",
    "BidSubmission",
    "BidTagQuery",
    "BidTaskListener",
    "BidTaskPoller",
    "BiddingClient",
    "BiddingError",
]

logger = logging.getLogger("orcade.bidding_client")

DEFAULT_TIMEOUT = (5, 30)  # (connect, read) seconds


# ----------------------------------------------------------------------
# Errors
# ----------------------------------------------------------------------

class BiddingError(Exception):
    """
    Any failure talking to the bidding service. ``status_code`` is the HTTP
    status returned by the server, or ``None`` when the request never got a
    response (connection refused, timeout, and so on).
    """

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code

    def __str__(self) -> str:
        if self.status_code is None:
            return self.message
        return f"[{self.status_code}] {self.message}"


# ----------------------------------------------------------------------
# Data classes
# ----------------------------------------------------------------------

def _parse_datetime(value: Any) -> Optional[datetime]:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def _format_datetime(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


@dataclass
class BidJob:
    """A bidding task, as returned by the server."""

    bid_job_id: str
    bid_job_name: Dict[str, Any] = field(default_factory=dict)
    bid_job_description: Dict[str, Any] = field(default_factory=dict)
    bid_job_metadata: Dict[str, Any] = field(default_factory=dict)
    bid_job_evaluator_id: str = ""
    bid_job_pqt_id: str = ""
    bid_job_tie_id: str = ""
    bid_job_creator_id: str = ""
    bid_job_subject_ids: List[str] = field(default_factory=list)
    bid_job_mode: str = "closed"
    bid_job_max_subjects: Optional[int] = None
    bid_job_max_time: Optional[int] = None
    bid_job_status: str = "open"
    bid_job_created_time: Optional[datetime] = None
    bid_job_closes_at: Optional[datetime] = None
    bid_job_tags: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BidJob":
        return cls(
            bid_job_id=data["bid_job_id"],
            bid_job_name=data.get("bid_job_name", {}),
            bid_job_description=data.get("bid_job_description", {}),
            bid_job_metadata=data.get("bid_job_metadata", {}),
            bid_job_evaluator_id=data.get("bid_job_evaluator_id", ""),
            bid_job_pqt_id=data.get("bid_job_pqt_id", ""),
            bid_job_tie_id=data.get("bid_job_tie_id", ""),
            bid_job_creator_id=data.get("bid_job_creator_id", ""),
            bid_job_subject_ids=list(data.get("bid_job_subject_ids", [])),
            bid_job_mode=data.get("bid_job_mode", "closed"),
            bid_job_max_subjects=data.get("bid_job_max_subjects"),
            bid_job_max_time=data.get("bid_job_max_time"),
            bid_job_status=data.get("bid_job_status", "open"),
            bid_job_created_time=_parse_datetime(data.get("bid_job_created_time")),
            bid_job_closes_at=_parse_datetime(data.get("bid_job_closes_at")),
            bid_job_tags=list(data.get("bid_job_tags", [])),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bid_job_id": self.bid_job_id,
            "bid_job_name": self.bid_job_name,
            "bid_job_description": self.bid_job_description,
            "bid_job_metadata": self.bid_job_metadata,
            "bid_job_evaluator_id": self.bid_job_evaluator_id,
            "bid_job_pqt_id": self.bid_job_pqt_id,
            "bid_job_tie_id": self.bid_job_tie_id,
            "bid_job_creator_id": self.bid_job_creator_id,
            "bid_job_subject_ids": list(self.bid_job_subject_ids),
            "bid_job_mode": self.bid_job_mode,
            "bid_job_max_subjects": self.bid_job_max_subjects,
            "bid_job_max_time": self.bid_job_max_time,
            "bid_job_status": self.bid_job_status,
            "bid_job_created_time": _format_datetime(self.bid_job_created_time),
            "bid_job_closes_at": _format_datetime(self.bid_job_closes_at),
            "bid_job_tags": list(self.bid_job_tags),
        }


@dataclass
class Bid:
    """One subject's bid on a bidding task, as returned by the server."""

    bid_id: str
    bid_job_id: str
    bid_subject_id: str
    bid_data: Dict[str, Any] = field(default_factory=dict)
    submission_time: Optional[datetime] = None
    is_winner: bool = False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Bid":
        return cls(
            bid_id=data["bid_id"],
            bid_job_id=data["bid_job_id"],
            bid_subject_id=data["bid_subject_id"],
            bid_data=data.get("bid_data", {}),
            submission_time=_parse_datetime(data.get("submission_time")),
            is_winner=bool(data.get("is_winner", False)),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bid_id": self.bid_id,
            "bid_job_id": self.bid_job_id,
            "bid_subject_id": self.bid_subject_id,
            "bid_data": self.bid_data,
            "submission_time": _format_datetime(self.submission_time),
            "is_winner": self.is_winner,
        }


@dataclass
class BidSubmission:
    """Input to :meth:`BiddingClient.submit_bid`."""

    bid_job_id: str
    bid_subject_id: str
    bid_data: Dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> Dict[str, Any]:
        # bid_job_id goes in the URL path, so it is not part of the body.
        return {"bid_subject_id": self.bid_subject_id, "bid_data": self.bid_data}


@dataclass
class BidTagQuery:
    """
    Input to the tag-based lookups.

    ``match="all"`` (default) returns jobs carrying every tag in ``tags``.
    ``match="any"`` returns jobs carrying at least one of them.
    """

    tags: List[str]
    match: str = "all"

    def __post_init__(self) -> None:
        if not self.tags:
            raise ValueError("BidTagQuery needs at least one tag.")
        for tag in self.tags:
            if not isinstance(tag, str) or not tag.strip():
                raise ValueError("Tags must be non-empty strings.")
            if "," in tag:
                # The server splits the tags parameter on commas.
                raise ValueError(f"Tag {tag!r} must not contain a comma.")
        if self.match not in ("all", "any"):
            raise ValueError("match must be 'all' or 'any'.")

    def to_params(self) -> Dict[str, str]:
        return {"tags": ",".join(t.strip() for t in self.tags), "match": self.match}


# ----------------------------------------------------------------------
# Listener protocol
# ----------------------------------------------------------------------

class BidTaskListener(Protocol):
    """
    Anything with an ``on_bidding_task`` method can receive poll results.
    The method is called on the poller's background thread.
    """

    def on_bidding_task(self, bid_task_data: BidJob) -> None:
        ...


# ----------------------------------------------------------------------
# Poller
# ----------------------------------------------------------------------

class BidTaskPoller:
    """
    Polls for bidding tasks matching a :class:`BidTagQuery` and hands each new
    one to ``listener.on_bidding_task``.

    - Every matching job is delivered once per poller. Jobs already seen are
      skipped on later polls.
    - With ``only_open=True`` (the default), jobs whose ``bid_job_status`` is
      not ``"open"`` are skipped. Closed open-mode jobs are never delivered.
      Closed-mode jobs stay ``"open"`` and are delivered as normal.
    - If the listener raises, the exception is logged and polling continues.
      That job is still marked as delivered and is not retried.
    - The first poll delivers every matching job that already exists.
    - Network or server errors are logged and retried on the next interval.
    - Listener calls run on the poller thread, so a slow listener delays the
      next poll.

    Use :meth:`BiddingClient.poll_bid_tasks` to create and start one.
    """

    def __init__(
        self,
        client: "BiddingClient",
        query: BidTagQuery,
        listener: BidTaskListener,
        *,
        interval_seconds: float = 10.0,
        only_open: bool = True,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive.")
        if not hasattr(listener, "on_bidding_task"):
            raise TypeError("listener must define an on_bidding_task(bid_task_data) method.")

        self._client = client
        self._query = query
        self._listener = listener
        self._interval = float(interval_seconds)
        self._only_open = only_open

        self._seen: set = set()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="orcade-bid-task-poller",
            daemon=True,
        )

    @property
    def running(self) -> bool:
        return self._thread.is_alive() and not self._stop_event.is_set()

    def start(self) -> "BidTaskPoller":
        if self._thread.is_alive():
            return self
        self._thread.start()
        return self

    def stop(self, timeout: Optional[float] = None) -> None:
        """Signal the poller to exit and wait up to ``timeout`` seconds."""
        self._stop_event.set()
        if self._thread.is_alive() and threading.current_thread() is not self._thread:
            self._thread.join(timeout)

    def poll_once(self) -> int:
        """
        Run a single poll synchronously and return how many jobs were
        delivered. The background thread calls this on every interval. It is
        also public so callers can drive polling manually.
        """
        jobs = self._client.find_bid_jobs_by_tags(self._query)
        delivered = 0
        for job in jobs:
            if job.bid_job_id in self._seen:
                continue
            if self._only_open and job.bid_job_status != "open":
                continue
            self._seen.add(job.bid_job_id)
            delivered += 1
            try:
                self._listener.on_bidding_task(job)
            except Exception:
                logger.exception(
                    "on_bidding_task failed for bid job %s", job.bid_job_id
                )
        return delivered

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.poll_once()
            except Exception:
                logger.exception("Bid task poll failed; retrying next interval")
            self._stop_event.wait(self._interval)


# ----------------------------------------------------------------------
# Client
# ----------------------------------------------------------------------

class BiddingClient:
    """
    Thin synchronous client over the bidding REST API.

    Every method takes and returns the dataclasses above. Server-side
    failures raise :class:`BiddingError`, with the HTTP status code attached
    (409 for a refused bid, 404 for an unknown job, and so on).
    """

    def __init__(
        self,
        base_url: str,
        *,
        timeout: Any = DEFAULT_TIMEOUT,
        session: Optional[requests.Session] = None,
    ) -> None:
        if not base_url or not str(base_url).strip():
            raise ValueError("base_url is required.")
        self.base_url = str(base_url).strip().rstrip("/")
        self._timeout = timeout
        self._session = session or requests.Session()

    # -- public API ----------------------------------------------------

    def submit_bid(self, submission: BidSubmission) -> Bid:
        """
        Submit a bid (or, for an open-mode job, apply to it).

        Raises :class:`BiddingError` with status 409 if the bid is refused by
        the PQT function, the job is closed or full, or the subject has
        already applied. Status 404 means the job does not exist.
        """
        data = self._request(
            "POST",
            f"/bid-jobs/{_path_segment(submission.bid_job_id)}/bids",
            json=submission.to_payload(),
        )
        return Bid.from_dict(data)

    def get_bid_job(self, bid_job_id: str) -> BidJob:
        """Query a single bidding task by its ID."""
        data = self._request("GET", f"/bid-jobs/{_path_segment(bid_job_id)}")
        return BidJob.from_dict(data)

    def find_bid_jobs_by_tags(self, query: BidTagQuery) -> List[BidJob]:
        """Query all bidding tasks matching the tags. An empty result is ``[]``."""
        data = self._request("GET", "/bid-jobs/by-tags", params=query.to_params())
        return [BidJob.from_dict(item) for item in data]

    def poll_bid_tasks(
        self,
        query: BidTagQuery,
        listener: BidTaskListener,
        *,
        interval_seconds: float = 10.0,
        only_open: bool = True,
    ) -> BidTaskPoller:
        """
        Start a background poller. Each new bidding task matching ``query`` is
        passed to ``listener.on_bidding_task(bid_task_data)`` as a
        :class:`BidJob`. Returns the running :class:`BidTaskPoller`. Call its
        ``stop()`` method to end polling.
        """
        poller = BidTaskPoller(
            self,
            query,
            listener,
            interval_seconds=interval_seconds,
            only_open=only_open,
        )
        return poller.start()

    # -- internals -----------------------------------------------------

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.base_url}{path}"
        try:
            resp = self._session.request(method, url, timeout=self._timeout, **kwargs)
        except requests.RequestException as e:
            raise BiddingError(f"Request to {url} failed: {e}") from e

        try:
            body = resp.json()
        except ValueError:
            raise BiddingError(
                f"Non-JSON response from server: {resp.text[:200]!r}",
                status_code=resp.status_code,
            )

        if not isinstance(body, dict) or not body.get("ok"):
            error = body.get("error", "unknown error") if isinstance(body, dict) else str(body)
            raise BiddingError(error, status_code=resp.status_code)

        return body.get("data")


def _path_segment(value: str) -> str:
    return quote(str(value), safe="")
