import logging
import time
import requests
from typing import Any, Dict, List, Optional, Tuple, Union
from .exceptions import (
    XchangeError,
    XchangeNetworkError,
    XchangeAPIError,
    XchangeTimeoutError,
)

# Sentinel distinguishing "argument omitted" from an explicit None.
#
# For timeout / log_level / poll_interval, None means "use the client default" --
# the convention the sibling openarcade SDK already uses. For wait_budget that
# convention collides with None meaning "wait forever", so wait_for_task defaults
# to this sentinel instead: omitted -> client default, None -> unbounded.
_UNSET = object()

# Lifecycle states that end a wait. Everything else -- including "pending",
# "assigned", "bidding" and any status this SDK does not recognise -- is treated
# as still in flight.
_TERMINAL_STATES = frozenset({"completed", "failed", "rejected"})


class XchangeClient:
    """
    Client for the Xchange exchange system's REST API.

    The exchange is a task board: it accepts tasks, decides which of its registered
    subjects should do the work (via one of four assignment strategies), hands the
    task off, and records the result.

    Responses are returned as the exchange sends them, envelope and all --
    ``{"ok": true, "data": {...}}`` -- rather than unwrapped, matching the sibling
    openarcade_bidding_pysdk.

    Timing: every wait this client performs draws its interval and budget from
    caller-settable values. Defaults are a 5 second poll interval, a 300 second wait
    budget and a 30 second request timeout; each is overridable per call.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:5000",
        log_level: int = logging.WARNING,
        timeout: Union[float, Tuple[float, float]] = 30,
        poll_interval: float = 5,
        wait_budget: Optional[float] = 300,
    ):
        """
        :param base_url: Address of the exchange. Any trailing separator is stripped.
        :param log_level: Default verbosity for this client's diagnostics.
        :param timeout: Default per-request timeout. Either a single number covering
            the whole exchange, or a ``(connect, read)`` pair.
        :param poll_interval: Default seconds between polls in ``wait_for_task``.
        :param wait_budget: Default seconds ``wait_for_task`` keeps polling before
            giving up. ``None`` means wait indefinitely.
        """
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        self.logger = logging.getLogger("xchange_sdk")
        if not self.logger.handlers:
            handler = logging.NullHandler()
            self.logger.addHandler(handler)
        self.logger.setLevel(log_level)
        self.default_log_level = log_level
        self.default_timeout = timeout
        self.default_poll_interval = poll_interval
        self.default_wait_budget = wait_budget

    def _request(
        self,
        method: str,
        path: str,
        timeout: Optional[Union[float, Tuple[float, float]]] = None,
        log_level: Optional[int] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}/{path.lstrip('/')}"
        eff_log_level = log_level if log_level is not None else self.default_log_level
        eff_timeout = timeout if timeout is not None else self.default_timeout
        self.logger.log(eff_log_level, f"Sending {method} request to {url}")

        try:
            response = self.session.request(method, url, timeout=eff_timeout, **kwargs)
            self.logger.log(eff_log_level, f"Received response {response.status_code} from {url}")
            if not response.ok:
                try:
                    err_data = response.json()
                except ValueError:
                    err_data = {}
                if not isinstance(err_data, dict):
                    err_data = {}
                msg = err_data.get('error', response.text)
                self.logger.error(f"API Error {response.status_code} on {method} {url}: {msg}")
                raise XchangeAPIError(
                    f"API Error: {msg}",
                    status_code=response.status_code,
                    payload=err_data,
                )
        except requests.RequestException as e:
            self.logger.error(f"Network error on {method} {url}: {e}")
            raise XchangeNetworkError(f"Network error: {str(e)}") from e

        try:
            data = response.json()
        except ValueError:
            self.logger.error(f"Non-JSON response from {url}: {response.text}")
            raise XchangeAPIError(f"Invalid JSON response: {response.text}")

        # The exchange always replies with a JSON object ({"ok": ..., "data"/"error": ...}).
        # A list, a string or a null means something other than the exchange answered --
        # a proxy error page, a truncated body -- and must not be handed back as a record.
        if not isinstance(data, dict):
            raise XchangeAPIError(f"Unexpected response structure: {data}")

        return data

    # --- Tasks ---

    def submit_task(
        self,
        task_assignment_type: str,
        task_data: Any,
        task_id: Optional[str] = None,
        task_assignment_status: Optional[str] = None,
        task_metadata: Optional[Dict[str, Any]] = None,
        timeout: Optional[Union[float, Tuple[float, float]]] = None,
        log_level: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        POST /tasks -- submit a task with an explicitly built assignment block.

        This is the generic form. For the four assignment strategies, prefer
        ``submit_direct_task`` / ``submit_function_task`` / ``submit_open_task`` /
        ``submit_bidding_task``, which assemble ``task_metadata.task_assignment``
        for you.

        Note this call **never waits for the work**. It returns as soon as the task is
        persisted (and, for ``function`` mode only, a subject has been selected). The
        record it returns is a snapshot taken at submission -- trust ``task_id`` from
        it and re-read with ``get_task`` for anything else.

        Optional arguments left as None are omitted from the request entirely, so the
        exchange applies its own defaults (server-generated ``task_id``, status
        ``"pending"``, metadata ``{}``).
        """
        payload: Dict[str, Any] = {
            "task_assignment_type": task_assignment_type,
            "task_data": task_data,
        }
        if task_id is not None:
            payload["task_id"] = task_id
        if task_assignment_status is not None:
            payload["task_assignment_status"] = task_assignment_status
        if task_metadata is not None:
            payload["task_metadata"] = task_metadata

        return self._request("POST", "tasks", json=payload, timeout=timeout, log_level=log_level)

    def get_task(
        self,
        task_id: str,
        timeout: Optional[Union[float, Tuple[float, float]]] = None,
        log_level: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        GET /tasks/{task_id} -- the full task record.

        The record's creation timestamp is spelled ``taski_creation_time``. That typo
        is upstream and intentional; it is passed through exactly as the exchange
        spells it.
        """
        return self._request("GET", f"tasks/{task_id}", timeout=timeout, log_level=log_level)

    def get_task_output(
        self,
        task_id: str,
        timeout: Optional[Union[float, Tuple[float, float]]] = None,
        log_level: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        GET /tasks/{task_id}/output -- just ``task_assignment_status`` and ``task_output``.

        This is the endpoint callers poll. There is no long-poll or websocket mode on
        the exchange; ``wait_for_task`` polls this on your behalf.
        """
        return self._request("GET", f"tasks/{task_id}/output", timeout=timeout, log_level=log_level)

    def query_tasks(
        self,
        filter_query: Dict[str, Any],
        timeout: Optional[Union[float, Tuple[float, float]]] = None,
        log_level: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        POST /tasks/query -- query tasks with a raw MongoDB filter document.

        The filter is forwarded to the exchange verbatim and reaches
        ``collection.find()`` unaltered, so any Mongo operator works (``$gt``, ``$in``,
        ``$ne``, ``$exists``). Field names are not rewritten -- a filter naming
        ``taski_creation_time`` must spell it exactly as the exchange stores it.

        The exchange offers no update or delete for tasks by design: task state is only
        ever mutated internally by its own assignment service. This SDK therefore
        exposes no ``update_task`` or ``delete_task``.
        """
        return self._request("POST", "tasks/query", json=filter_query, timeout=timeout, log_level=log_level)

    # --- Assignment strategies ---

    @staticmethod
    def _with_assignment(
        task_metadata: Optional[Dict[str, Any]],
        assignment: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        Merge a strategy's assignment block into the caller's task metadata.

        The caller's dict is copied, never mutated -- example scripts commonly build one
        metadata dict and submit several tasks with it, and in-place mutation would leak
        one task's assignment into the next. The caller's other keys survive; the
        helper's ``task_assignment`` wins over a caller-supplied one, since owning that
        key correctly is the whole point of these helpers.

        An empty assignment (``open`` mode) adds no key at all.
        """
        if not assignment:
            return dict(task_metadata) if task_metadata is not None else None
        merged = dict(task_metadata) if task_metadata is not None else {}
        merged["task_assignment"] = assignment
        return merged

    def submit_direct_task(
        self,
        task_data: Any,
        subject_id: str,
        task_id: Optional[str] = None,
        task_metadata: Optional[Dict[str, Any]] = None,
        timeout: Optional[Union[float, Tuple[float, float]]] = None,
        log_level: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Submit a task pinned to one named subject (``task_assignment_type="direct"``).

        No selection logic runs at all -- the caller already knows who should do the
        work. The only asynchronous part is the delegate round-trip; this call returns
        as soon as the task is persisted.
        """
        assignment = {"subject_id": subject_id}
        return self.submit_task(
            task_assignment_type="direct",
            task_data=task_data,
            task_id=task_id,
            task_metadata=self._with_assignment(task_metadata, assignment),
            timeout=timeout,
            log_level=log_level,
        )

    def submit_function_task(
        self,
        task_data: Any,
        function_id: str,
        parameters: Optional[Dict[str, Any]] = None,
        task_id: Optional[str] = None,
        task_metadata: Optional[Dict[str, Any]] = None,
        timeout: Optional[Union[float, Tuple[float, float]]] = None,
        log_level: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Submit a task whose subject is chosen by a selector function
        (``task_assignment_type="function"``).

        This is the **only mode with a synchronous step**: the selector function is
        invoked inline inside the exchange's own request handler, with the task and the
        full subject list. If it raises, or returns no truthy ``selected_subject_id``,
        this call itself fails with an ``XchangeAPIError`` (status 400) -- and the task
        is still persisted, marked ``failed``, readable afterwards via ``get_task``.
        No subject is notified in that case.

        ``parameters`` is forwarded to the function. Note the exchange drops it for
        functions registered in *external* HTTP mode; it only reaches stateful and
        stateless functions.
        """
        assignment: Dict[str, Any] = {"function_id": function_id}
        if parameters is not None:
            assignment["parameters"] = parameters
        return self.submit_task(
            task_assignment_type="function",
            task_data=task_data,
            task_id=task_id,
            task_metadata=self._with_assignment(task_metadata, assignment),
            timeout=timeout,
            log_level=log_level,
        )

    def submit_open_task(
        self,
        task_data: Any,
        task_id: Optional[str] = None,
        task_metadata: Optional[Dict[str, Any]] = None,
        timeout: Optional[Union[float, Tuple[float, float]]] = None,
        log_level: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Submit a task offered to every subject in turn (``task_assignment_type="open"``).

        Takes no assignment parameters -- the exchange ignores ``task_assignment``
        entirely for this mode, so none is sent. Each subject's own
        ``task_evaluation_function`` is asked in sequence (not in parallel) until one
        answers ``"accepted"``; subjects with no evaluation function are skipped
        entirely.

        If no subject accepts, the task settles at ``task_assignment_status="rejected"``
        with an explanation in ``task_output.error``. That is a normal terminal state,
        not a failure of this call.
        """
        return self.submit_task(
            task_assignment_type="open",
            task_data=task_data,
            task_id=task_id,
            task_metadata=self._with_assignment(task_metadata, {}),
            timeout=timeout,
            log_level=log_level,
        )

    def submit_bidding_task(
        self,
        task_data: Any,
        bid_job_evaluator_id: str,
        bid_job_subject_ids: Optional[List[str]] = None,
        bid_job_pqt_id: Optional[str] = None,
        bid_job_tie_id: Optional[str] = None,
        bid_job_metadata: Optional[Dict[str, Any]] = None,
        bid_job_description: Optional[Dict[str, Any]] = None,
        bid_job_name: Optional[Dict[str, Any]] = None,
        bid_job_creator_id: Optional[str] = None,
        topics: Optional[List[str]] = None,
        task_id: Optional[str] = None,
        task_metadata: Optional[Dict[str, Any]] = None,
        timeout: Optional[Union[float, Tuple[float, float]]] = None,
        log_level: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Submit a task whose subject is chosen by Orcade's bidding system
        (``task_assignment_type="bidding"``).

        The exchange opens a bid job on the caller's behalf and polls it until a winner
        emerges. This SDK never talks to Orcade directly.

        **Who ends up in the bid job.** The exchange resolves the subject set in
        priority order (exchange-system docs, 07-bidding-mode.md 7.2):

        1. ``bid_job_subject_ids`` -- an explicit list, used verbatim if given.
        2. otherwise ``topics`` -- every subject whose own ``topics`` field intersects
           this one, i.e. the subject query ``{"topics": {"$in": topics}}``. A subject
           tags itself via ``create_subject(topics=[...])``.
        3. otherwise every subject currently registered in the exchange.

        Passing an explicit empty ``bid_job_subject_ids`` instead opens a bid job with
        no subjects at all, which will never resolve -- so omit it unless you really
        mean to name a subset. The list is captured once at bid-job creation; a subject
        registered or re-tagged afterwards is not added retroactively.

        .. warning::
           Passing **both** ``bid_job_subject_ids`` and ``topics`` currently resolves to
           the explicit list alone -- the exchange short-circuits at step 1 and never
           runs the topic query. Callers wanting "these named subjects *plus* whoever is
           listening on this topic" need the exchange to union steps 1 and 2; until it
           does, the topic-matched subjects are silently absent from the bid job. Check
           the resolved ``bid_job_subject_ids`` on the bid job rather than assuming.

        **This mode has no server-side timeout.** Orcade only evaluates once *every*
        named subject has bid, so if one never bids the task sits in
        ``task_assignment_status="bidding"`` forever. Only your own ``wait_budget`` in
        ``wait_for_task`` ends the wait. To debug a stuck job, read
        ``task_metadata.bid_job_id`` off the task and query Orcade directly -- the
        sibling ``openarcade_bidding_pysdk`` covers that API.
        """
        assignment: Dict[str, Any] = {"bid_job_evaluator_id": bid_job_evaluator_id}
        optional = {
            "bid_job_subject_ids": bid_job_subject_ids,
            "bid_job_pqt_id": bid_job_pqt_id,
            "bid_job_tie_id": bid_job_tie_id,
            "bid_job_metadata": bid_job_metadata,
            "bid_job_description": bid_job_description,
            "bid_job_name": bid_job_name,
            "bid_job_creator_id": bid_job_creator_id,
            "topics": topics,
        }
        for key, value in optional.items():
            if value is not None:
                assignment[key] = value

        return self.submit_task(
            task_assignment_type="bidding",
            task_data=task_data,
            task_id=task_id,
            task_metadata=self._with_assignment(task_metadata, assignment),
            timeout=timeout,
            log_level=log_level,
        )

    # --- Subjects ---

    def create_subject(
        self,
        subject_id: Optional[str] = None,
        subject_metadata: Optional[Dict[str, Any]] = None,
        task_evaluation_function: Optional[str] = None,
        subject_capabilities: Optional[Dict[str, Any]] = None,
        topics: Optional[List[str]] = None,
        timeout: Optional[Union[float, Tuple[float, float]]] = None,
        log_level: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        POST /subjects -- register an agent that can receive tasks.

        There is no separate "join the exchange" workflow; creating this record is all
        there is to it.

        ``task_evaluation_function`` is the registry id of the function asked whether
        this subject accepts a given task, and is consulted **only** by ``open`` mode.
        A subject without one is skipped entirely during open evaluation.

        ``topics`` tags this subject so a ``bidding``-mode task can pull it into a bid
        job without naming it explicitly -- see ``submit_bidding_task``. The exchange
        matches with ``{"topics": {"$in": [...]}}``, so any one overlapping tag is
        enough. It is consulted by no other assignment mode. Find every subject
        carrying a tag with ``query_subjects({"topics": {"$in": ["<tag>"]}})``.

        Fields left as None are omitted, so the exchange applies its own defaults: a
        server-generated ``subject_id``, ``{}`` metadata, ``""`` evaluation function,
        ``{}`` capabilities and ``[]`` topics.
        """
        payload: Dict[str, Any] = {}
        optional = {
            "subject_id": subject_id,
            "subject_metadata": subject_metadata,
            "task_evaluation_function": task_evaluation_function,
            "subject_capabilities": subject_capabilities,
            "topics": topics,
        }
        for key, value in optional.items():
            if value is not None:
                payload[key] = value

        return self._request("POST", "subjects", json=payload, timeout=timeout, log_level=log_level)

    def get_subject(
        self,
        subject_id: str,
        timeout: Optional[Union[float, Tuple[float, float]]] = None,
        log_level: Optional[int] = None,
    ) -> Dict[str, Any]:
        """GET /subjects/{subject_id}"""
        return self._request("GET", f"subjects/{subject_id}", timeout=timeout, log_level=log_level)

    def update_subject(
        self,
        subject_id: str,
        updates: Dict[str, Any],
        timeout: Optional[Union[float, Tuple[float, float]]] = None,
        log_level: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        PATCH /subjects/{subject_id} -- apply a raw MongoDB ``$set`` update.

        ``updates`` is forwarded verbatim, including dotted paths. The exchange checks
        the subject exists first (404 if not) and returns the *refreshed* document
        rather than a modified count.
        """
        return self._request(
            "PATCH", f"subjects/{subject_id}", json=updates, timeout=timeout, log_level=log_level
        )

    def delete_subject(
        self,
        subject_id: str,
        timeout: Optional[Union[float, Tuple[float, float]]] = None,
        log_level: Optional[int] = None,
    ) -> Dict[str, Any]:
        """DELETE /subjects/{subject_id} -- 404 if the subject did not exist."""
        return self._request("DELETE", f"subjects/{subject_id}", timeout=timeout, log_level=log_level)

    def query_subjects(
        self,
        filter_query: Dict[str, Any],
        timeout: Optional[Union[float, Tuple[float, float]]] = None,
        log_level: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        POST /subjects/query -- query subjects with a raw MongoDB filter document.

        Forwarded verbatim, same convention as ``query_tasks``. For example,
        ``{"task_evaluation_function": {"$ne": ""}}`` finds every subject that
        participates in open-mode evaluation.
        """
        return self._request(
            "POST", "subjects/query", json=filter_query, timeout=timeout, log_level=log_level
        )

    # --- Waiting for an outcome ---

    def wait_for_task(
        self,
        task_id: str,
        poll_interval: Optional[float] = None,
        wait_budget: Optional[float] = _UNSET,
        timeout: Optional[Union[float, Tuple[float, float]]] = None,
        log_level: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Poll ``GET /tasks/{task_id}/output`` until the task reaches a terminal state.

        The exchange never blocks a submission on the actual work -- every strategy
        resolves on its own schedule and the documented way to learn the outcome is to
        poll. This does that polling for you.

        Returns the reply envelope whole as soon as ``task_assignment_status`` is
        ``completed``, ``failed`` or ``rejected``. All three are settled answers:
        ``failed`` carries the error in ``task_output.error``, and ``rejected`` is
        ``open`` mode's normal outcome when no subject accepted. **None of them raise**
        -- only budget exhaustion does.

        :param poll_interval: Seconds between polls. None uses the client default (5).
        :param wait_budget: Seconds to keep polling.

            * omitted   -> the client default (300)
            * a number  -> that many seconds
            * ``None``  -> wait indefinitely

            The default stays finite deliberately, so an unbounded wait is only ever
            reached by explicitly passing None -- never by omission. Unbounded is the
            exchange's own behaviour for ``bidding`` mode, which has no server-side
            timeout of any kind.

        :raises XchangeTimeoutError: the budget ran out before the task settled. Carries
            ``task_id`` and ``last_status`` so you can see how far it got.
        :raises XchangeAPIError: the task does not exist (404). A missing task is not
            transient, so it is re-raised at once rather than polled through.

        Transient failures mid-wait -- a brief network blip, a 5xx, an uninterpretable
        reply -- are logged and retried until the budget runs out, mirroring how the
        exchange itself polls Orcade.
        """
        eff_poll_interval = poll_interval if poll_interval is not None else self.default_poll_interval
        eff_budget = self.default_wait_budget if wait_budget is _UNSET else wait_budget
        eff_log_level = log_level if log_level is not None else self.default_log_level

        deadline = None if eff_budget is None else time.monotonic() + eff_budget
        last_status = None

        while True:
            try:
                envelope = self.get_task_output(task_id, timeout=timeout, log_level=log_level)
                last_status = (envelope.get("data") or {}).get("task_assignment_status")
                if last_status in _TERMINAL_STATES:
                    self.logger.log(eff_log_level, f"Task {task_id} settled as {last_status}")
                    return envelope
            except XchangeAPIError as e:
                # A missing task will never appear; polling it for the full budget and
                # then reporting a timeout would be the wrong diagnosis.
                if e.status_code == 404:
                    raise
                self.logger.debug(f"Transient error polling task {task_id}: {e}")
            except XchangeError as e:
                self.logger.debug(f"Transient error polling task {task_id}: {e}")

            if deadline is not None and time.monotonic() + eff_poll_interval > deadline:
                raise XchangeTimeoutError(
                    f"Task {task_id} did not settle within {eff_budget} seconds "
                    f"(last status: {last_status})",
                    task_id=task_id,
                    last_status=last_status,
                )

            time.sleep(eff_poll_interval)
