"""How a Bid Manager reaches OpenArcade, and how a company finds work by polling.

Two routes lead to a bid job, and one company can be reached by both at once:

  * **`bid_request`** -- OpenArcade sends it to every subject on the job's roster. It is
    the primary route, and the only one the three companies invited by name rely on.
  * **Polling** -- `GET /bid-jobs/by-tags`. A company that listens on a topic
    (UltraVideoTech, VideoProcTech) asks for jobs carrying that topic or naming it.
    In `open` mode this is the only way a company ever hears of a job. In `mixed` mode it
    is a second route to a job the company is already on the roster of, so a lost
    `bid_request` does not cost the company its bid.

A bid costs a full six-agent run, so both routes share one rule: **a job is claimed
exactly once.** `Discovery.claim` is that rule, and both routes go through it.

Settings come from the pod's environment first and from the agent's own spec
(`persona.config.parameters`) second, so a value set at deployment time wins and the spec
only fills what is absent.
"""
import atexit
import logging
import os
import threading
import time
from typing import List, Optional

from agents_sdk.core.bidding_client import BidTagQuery, BidTaskPoller

from . import spec_env

log = logging.getLogger(__name__)

DEFAULT_POLL_SECONDS = 10.0

# The bid_request for a roster job normally arrives within moments of the job being
# created. A polled roster job therefore waits this long for it before taking over, so the
# two routes do not both start the same six-agent run.
ROSTER_GRACE_SECONDS = 30.0

# OpenArcade runs the pre-qualification function as a Kubernetes job inside the
# submit call, and with five Bid Managers submitting at once that has taken longer than the
# client's default 30s read timeout. A timeout here is not harmless: the submission may
# have landed, and the retry then finds its own bid already on file. Waiting is cheaper.
SUBMIT_TIMEOUT = (5, 120)

# Closed and mixed jobs have a fixed roster set at creation; open jobs have none.
ROSTER_MODES = ("closed", "mixed")


# --- settings ---------------------------------------------------------------

def _usable(value) -> Optional[str]:
    """A setting's text, or None when it is absent or an unexpanded `${...}` placeholder."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.startswith("${"):
        return None
    return text


def _from_spec(subject, name) -> Optional[str]:
    return _usable(spec_env.parameters(subject).get(name))


def url(subject) -> Optional[str]:
    """OpenArcade's base URL: the pod's `ORCADE_URL`, else the spec's."""
    return _usable(os.environ.get("ORCADE_URL")) or _from_spec(subject, "ORCADE_URL")


def poll_seconds(subject) -> float:
    """Seconds between polls: the pod's `ORCADE_POLL_SECONDS`, else the spec's, else 10."""
    raw = _usable(os.environ.get("ORCADE_POLL_SECONDS")) or _from_spec(subject, "ORCADE_POLL_SECONDS")
    if raw is None:
        return DEFAULT_POLL_SECONDS
    try:
        value = float(raw)
    except ValueError:
        log.warning("ORCADE_POLL_SECONDS=%r is not a number; using %.0fs", raw, DEFAULT_POLL_SECONDS)
        return DEFAULT_POLL_SECONDS
    if value <= 0:
        log.warning("ORCADE_POLL_SECONDS=%r is not positive; using %.0fs", raw, DEFAULT_POLL_SECONDS)
        return DEFAULT_POLL_SECONDS
    return value


def topics(subject) -> List[str]:
    """The topics this agent listens on: `metadata.subject_metadata.topics` in its spec.

    Deliberately not `subject_search_tags`. Those are generic labels for searching and
    querying agents -- the Bid Manager itself uses one to find its own subordinates --
    and say nothing about what an agent has been told to listen to.
    """
    metadata = getattr(getattr(subject, "metadata", None), "subject_metadata", None)
    raw = metadata.get("topics") if isinstance(metadata, dict) else None
    if isinstance(raw, str):
        raw = raw.split(",")
    if not isinstance(raw, (list, tuple)):
        return []
    found = []
    for item in raw:
        text = str(item).strip()
        # The server splits the tags parameter on commas, so a tag cannot contain one.
        if text and "," not in text and text not in found:
            found.append(text)
    return found


# --- finding work -----------------------------------------------------------

class Discovery:
    """Claims jobs for one Bid Manager, and polls for the ones its topics name.

    The poller delivers to `on_bidding_task` on its own thread, which is where this hands
    the job to the agent. Whether a polled job should be bid on at all is `admit`'s call.
    """

    def __init__(self, subject_id, topic_list, interval=DEFAULT_POLL_SECONDS, *,
                 grace=ROSTER_GRACE_SECONDS, tick=1.0):
        self.subject_id = subject_id
        self.topics = list(topic_list or [])
        self.interval = interval
        self.grace = grace
        self._tick = tick

        self._claimed = set()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._listener = None
        self._poller = None
        self._thread = None
        self._warming = True
        self.ignored = set()        # roster jobs that already existed when polling began

    # -- one claim per job, whichever route finds it first -------------------

    def claim(self, bid_job_id) -> bool:
        """True if this caller now owns the job; False if the other route already does."""
        if not bid_job_id:
            return True
        with self._lock:
            if bid_job_id in self._claimed:
                return False
            self._claimed.add(bid_job_id)
            return True

    def is_claimed(self, bid_job_id) -> bool:
        with self._lock:
            return bid_job_id in self._claimed

    def admit(self, job) -> Optional[str]:
        """Why a polled job should NOT be bid on, or None when it should (and is claimed).

        May wait up to `grace` seconds, on the poller thread.
        """
        mode = (job.bid_job_mode or "closed").lower()
        on_roster = self.subject_id in (job.bid_job_subject_ids or [])

        if mode in ROSTER_MODES:
            if not on_roster:
                # OpenArcade would refuse the bid, and the run to produce it is wasted.
                return f"{mode}-mode job and {self.subject_id} is not on its roster"
            # The bid_request is the primary route. Give it a chance before taking over.
            deadline = time.monotonic() + self.grace
            while time.monotonic() < deadline:
                if self.is_claimed(job.bid_job_id):
                    return "its bid_request is already being handled"
                if self._stop.wait(self._tick):
                    return "stopping"
        elif on_roster:
            return "already applied to this open job"

        if not self.claim(job.bid_job_id):
            return "already claimed"
        return None

    # -- the poller ----------------------------------------------------------

    def start(self, listener, client) -> bool:
        """Begin polling for this agent's topics. False if there is nothing to poll for."""
        if not self.topics:
            log.info("%s listens on no topics; polling is off, bid_request only", self.subject_id)
            return False
        if client is None:
            log.error("%s listens on %s but has no OpenArcade client (ORCADE_URL unset); "
                      "polling is off", self.subject_id, self.topics)
            return False
        if self._thread is not None:
            return True
        try:
            # Jobs matching a topic OR naming this subject (mixed-mode jobs carry a
            # `subject::<id>` tag for every subject on their roster).
            query = BidTagQuery(tags=self.topics, subject_id=self.subject_id, match="any")
            self._poller = BidTaskPoller(client, query, self, interval_seconds=self.interval)
        except (ValueError, TypeError) as e:
            log.error("%s: cannot poll for %s (%s)", self.subject_id, self.topics, e)
            return False
        self._listener = listener
        self._thread = threading.Thread(target=self._bootstrap, name="orcade-poll-bootstrap",
                                        daemon=True)
        self._thread.start()
        # The SDK's own signal handler stops only the Redis worker and knows nothing about
        # this thread, so stop it when the interpreter exits.
        atexit.register(self.stop)
        return True

    def on_bidding_task(self, job) -> None:
        """The poller's listener. While warming up, roster jobs are history, not work."""
        if self._warming and (job.bid_job_mode or "closed").lower() in ROSTER_MODES:
            self.ignored.add(job.bid_job_id)
            return
        if self._listener is not None:
            self._listener.on_bidding_task(job)

    def _bootstrap(self) -> None:
        """Learn what already exists, then poll for what is new.

        OpenArcade reports a closed or mixed job as `open` for ever, even after it has
        been evaluated, and the poller's first poll hands over everything that matches.
        Without this, every restart would put the whole six-agent run through for each
        round the company has ever taken part in. So the first poll is taken as the
        baseline: roster jobs found in it are ignored, and only jobs created afterwards
        are bid on. (Open jobs are not ignored -- their status is accurate, and one that
        is still open is one the company may yet apply to.)

        A server that cannot answer yet -- polling needs `/bid-jobs/by-tags`, which an
        older OpenArcade lacks -- is retried quietly until it can.
        """
        failures = 0
        while not self._stop.is_set():
            try:
                self._poller.poll_once()
                break
            except Exception as e:
                failures += 1
                log.log(logging.WARNING if failures == 1 else logging.DEBUG,
                        "%s: polling for %s is not available yet (%s); retrying every %.0fs",
                        self.subject_id, self.topics, e, self.interval)
                if self._stop.wait(self.interval):
                    return
        else:
            return
        self._warming = False
        log.info("%s: polling OpenArcade every %.0fs for topics %s (%d existing roster job(s) "
                 "ignored)", self.subject_id, self.interval, self.topics, len(self.ignored))
        self._poller.start()

    def stop(self, timeout=5) -> None:
        self._stop.set()
        if self._poller is not None:
            self._poller.stop(timeout)
