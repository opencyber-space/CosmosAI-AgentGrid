import re
import json
import time
import logging
import threading
from uuid import uuid4
from typing import Any, Dict, List, Optional, Tuple
from queue import Queue, Empty

import requests

from .schema import FunctionEntry
from .functions_remote import FunctionCaller                
from .db_client import FunctionsRegistryClient 

logger = logging.getLogger("AgentFunctions")
logger.setLevel(logging.INFO)


class ResultHandle:
    def __init__(self) -> None:
        self._q: Queue = Queue(maxsize=1)

    def _set_ok(self, value: Dict[str, Any]) -> None:
        self._q.put(("ok", value))

    def _set_err(self, err: BaseException) -> None:
        self._q.put(("err", err))

    def wait(self, timeout: Optional[float] = None) -> Dict[str, Any]:
      
        status, payload = self._q.get(timeout=timeout)
        if status == "ok":
            return payload
        raise payload


class AgentFunctions:
    

    def __init__(
        self,
        functions_registry_url: str,
        *,
        executor_id: str,
        unique_parameter: str,
        num_workers: int = 4,
        default_stateful_replicas: int = 1,
        default_stateful_autoscaling: bool = False,
        default_headers: Optional[Dict[str, str]] = None,
        timeout: Tuple[int, int] = (600, 600),
    ):
       
        self._executor_id = executor_id
        self._unique_parameter = unique_parameter
        self._default_replicas = int(default_stateful_replicas)
        self._default_autoscaling = bool(default_stateful_autoscaling)

        # Initialize clients internally, per requirements
        self._registry = FunctionsRegistryClient(
            base_url=functions_registry_url,
            timeout=timeout,
        )
        self._caller = FunctionCaller(
            base_url=functions_registry_url,
            timeout=timeout,
            default_headers=default_headers or {},
            executor_id=self._executor_id
        )

        # Local state
        self._functions: Dict[str, FunctionEntry] = {}     # function_id -> FunctionEntry
        self._deployment_cache: Dict[str, str] = {}        # function_id -> deployment_id
        self._lock = threading.RLock()

        # Async worker pool
        self._task_q: Queue = Queue()
        self._stop_evt = threading.Event()
        self._workers: List[threading.Thread] = []
        self._start_workers(int(num_workers))

 
    def add(self, function_id: str) -> FunctionEntry:
        
        entry = self._registry.get_function(function_id)
        if entry is None:
            raise ValueError(f"Function '{function_id}' not found in registry.")
        if not entry.function_id:
            entry.generate_function_id()

        with self._lock:
            self._functions[entry.function_id] = entry

        logger.info("Added function: %s (stateful=%s external=%s)",
                    entry.function_id, entry.is_stateful, entry.is_external)
        return entry

    def remove(self, function_id: str, *, remove_deployment: bool = False) -> bool:
       
        with self._lock:
            entry = self._functions.pop(function_id, None)

        if not entry:
            logger.warning("remove: function_id '%s' not present locally.", function_id)
            return False

        if remove_deployment and entry.is_stateful:
            dep_id = None
            with self._lock:
                dep_id = self._deployment_cache.get(function_id)

            if dep_id:
                try:
                    logger.info("Removing deployment '%s' for function '%s'.", dep_id, function_id)
                    self._caller.remove_deployment(dep_id, function_id=function_id)
                except requests.HTTPError as e:
                    logger.error("Failed to remove deployment '%s' for '%s': %s", dep_id, function_id, e)
                finally:
                    with self._lock:
                        self._deployment_cache.pop(function_id, None)

        logger.info("Removed function: %s", function_id)
        return True

    def list(self) -> List[FunctionEntry]:
        with self._lock:
            return list(self._functions.values())

 
    def call(
        self,
        function_id: str,
        input_data: Dict[str, Any],
        *,
        job_name: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
        node_selector: Optional[Dict[str, Any]] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
              
        with self._lock:
            entry = self._functions.get(function_id)

        if not entry:
            raise ValueError(f"Function '{function_id}' not found locally. Add it first via add('{function_id}').")

        # (1.4) External function
        if entry.is_external:
            return self._call_external(entry, input_data)

        # (1.2) Stateful
        if entry.is_stateful:
            with self._lock:
                dep_id = self._deployment_cache.get(function_id)

            if not dep_id:
                dep_id = self._compose_deployment_name(entry.function_name, self._unique_parameter)
                logger.info("Creating deployment '%s' for stateful function '%s'.", dep_id, function_id)

                resp = None
                try:
                    resp = self._caller.create_deployment(
                        dep_id,
                        function_id=function_id,
                        name=dep_id,
                        replicas=self._default_replicas,
                        autoscaling=self._default_autoscaling,
                        function_metadata=entry.function_metadata or None,
                        function_tags=entry.function_tags or None,
                        extra_headers=extra_headers,
                    )

                    logger.info("[deployed_function] {}".format(resp))

                    while True:
                        try:
                            resp = self._caller.ping_function(function_id=dep_id)
                            if 'success' in resp and resp['success']:
                                break
                            logger.info(resp)
                            #break
                            time.sleep(4)
                            
                        except Exception as e:
                            logger.info(f"[PING], waiting for function to be live: {e}")
                            time.sleep(4)
                                                  

                    logger.info(f"[SUCCESS] Function deployment success: {resp}")

                except Exception as e:
                    logger.info(f"[WARNING] Function deployment failed: {resp}")
                with self._lock:
                    self._deployment_cache[function_id] = dep_id

            call_id = f"call-{uuid4().hex[:12]}"
            logger.info("Calling stateful function '%s' (call_id=%s).", function_id, call_id)

            input_data.update({"parameters": parameters})

            return self._caller.call_function(
                function_id=dep_id,
                args=input_data,
                extra_headers=extra_headers,
            )

        job = job_name or f"job-{uuid4().hex[:12]}"
        logger.info("Calling stateless function '%s' as job '%s'.", function_id, job)

        input_data.update({"parameters": parameters})
        return self._caller.call_function_as_job(
            self._executor_id,
            function_id=function_id,
            inputs=input_data,
            job_name=job,
            parameters=parameters,
            node_selector=node_selector,
            extra_headers=extra_headers,
        )


    def execute_async(
        self,
        function_id: str,
        input_data: Dict[str, Any],
        *,
        job_name: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
        node_selector: Optional[Dict[str, Any]] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> ResultHandle:

        handle = ResultHandle()
        task = (
            function_id,
            input_data,
            {"job_name": job_name, "parameters": parameters, "node_selector": node_selector, "extra_headers": extra_headers},
            handle,
        )
        self._task_q.put(task)
        return handle

    def shutdown(self, wait: bool = True) -> None:
        """Stop all workers."""
        self._stop_evt.set()
        # Push sentinel N times to unblock any waiting workers
        for _ in self._workers:
            self._task_q.put(None)
        if wait:
            for t in self._workers:
                t.join()

  
    def clear_all(self) -> Dict[str, Tuple[bool, Optional[str]]]:
       
        results: Dict[str, Tuple[bool, Optional[str]]] = {}
        with self._lock:
            pairs = [(fid, self._deployment_cache.get(fid)) for fid, e in self._functions.items() if e.is_stateful]

        for function_id, dep_id in pairs:
            if not dep_id:
                results[function_id] = (True, None)
                continue
            try:
                logger.info("Clearing deployment '%s' for function '%s'.", dep_id, function_id)
                self._caller.remove_deployment(dep_id, function_id=function_id)
                results[function_id] = (True, None)
            except requests.HTTPError as e:
                logger.error("Failed to remove deployment '%s' for '%s': %s", dep_id, function_id, e)
                results[function_id] = (False, str(e))
            finally:
                with self._lock:
                    self._deployment_cache.pop(function_id, None)
        return results



    def _start_workers(self, n: int) -> None:
        for i in range(max(1, n)):
            t = threading.Thread(target=self._worker_loop, name=f"agent-fn-worker-{i}", daemon=True)
            t.start()
            self._workers.append(t)

    def _worker_loop(self) -> None:
        while not self._stop_evt.is_set():
            task = self._task_q.get()
            if task is None:  # sentinel
                break
            function_id, input_data, opts, handle = task
            try:
                result = self.call(
                    function_id,
                    input_data,
                    job_name=opts.get("job_name"),
                    parameters=opts.get("parameters"),
                    node_selector=opts.get("node_selector"),
                    extra_headers=opts.get("extra_headers"),
                )
                handle._set_ok(result)
            except BaseException as e:
                handle._set_err(e)
            finally:
                self._task_q.task_done()

    def _call_external(self, entry: FunctionEntry, input_data: Dict[str, Any]) -> Dict[str, Any]:
        url = entry.external_function_url
        headers = {str(k): str(v) for k, v in (entry.external_headers or {}).items()}

        logger.info("Calling external function '%s' at '%s'.", entry.function_id, url)
        resp = self._caller.session.post(url, json=input_data, headers=headers, timeout=self._caller.timeout)
        try:
            resp.raise_for_status()
        except requests.HTTPError as e:
            body = None
            try:
                body = resp.text
            except Exception:
                pass
            raise requests.HTTPError(f"{e} | body={body}") from e

        try:
            data = resp.json()
        except Exception as e:
            logger.error("External function returned non-JSON response: %s", e)
            raise

        if not isinstance(data, dict) or "data" not in data:
            logger.warning("External response missing 'data'; returning raw JSON.")
            return data

        return data["data"]

    @staticmethod
    def _compose_deployment_name(function_name: str, unique_parameter: str) -> str:
       
        base = f"{function_name}-{unique_parameter}".lower()
        s = re.sub(r"[^a-z0-9-]", "-", base)
        s = re.sub(r"-{2,}", "-", s)
        s = s[:63]
        s = re.sub(r"^[^a-z0-9]+", "", s)
        s = re.sub(r"[^a-z0-9]+$", "", s)
        if not s:
            s = "fn-" + uuid4().hex[:8]
        return s
