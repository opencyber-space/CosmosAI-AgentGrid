import logging
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import requests

logger = logging.getLogger("FunctionCaller")
logger.setLevel(logging.INFO)


class FunctionCaller:

    def __init__(
        self,
        base_url: str,
        *,
        timeout: Tuple[int, int] = (600, 600),
        session: Optional[requests.Session] = None,
        default_headers: Optional[Dict[str, str]] = None,
        executor_id=""
    ):

        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()
        self.default_headers = default_headers or {}
        self.executor_id = executor_id

    def create_deployment(
        self,
        deployment_id: str,
        *,
        function_id: str,
        name: Optional[str] = None,
        policy_rule_parameters: Optional[Dict[str, Any]] = None,
        replicas: Optional[int] = None,
        autoscaling: Optional[bool] = None,
        function_metadata: Optional[Dict[str, Any]] = None,
        function_tags: Optional[List[str]] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:

        url = self._url(
            f"/function/deployments/create/{self.executor_id}")
        payload: Dict[str, Any] = {"function_id": function_id}

        if name is not None:
            payload["name"] = name
        if policy_rule_parameters is not None:
            payload["policy_rule_parameters"] = policy_rule_parameters
        if replicas is not None:
            payload["replicas"] = int(replicas)
        if autoscaling is not None:
            payload["autoscaling"] = bool(autoscaling)
        if function_metadata is not None:
            payload["function_metadata"] = function_metadata
        if function_tags is not None:
            payload["function_tags"] = function_tags

        resp = self.session.post(
            url, json=payload, timeout=self.timeout, headers=self._headers(
                extra_headers)
        )
        self._raise_for_status(resp)
        return self._safe_json(resp)

    def call_function(
        self,
        *,
        function_id: str,
        args: Optional[Dict[str, Any]] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:

        url = self._url(f"/function/call_function/{function_id}")
        payload: Dict[str, Any] = {"function_id": function_id}
        if args:
            # Merge user args (they may override, but 'function_id' stays)
            payload.update(args)

        resp = self.session.post(
            url, json=payload, timeout=self.timeout, headers=self._headers(
                extra_headers)
        )
        self._raise_for_status(resp)
        result = self._safe_json(resp)
        return result.get("data", result)
    
    def ping_function(
        self,
        *,
        function_id: str
    ) -> Dict[str, Any]:

        url = self._url(f"/function/ping_function/{function_id}")
      
        resp = self.session.get(url)
        self._raise_for_status(resp)
        result = self._safe_json(resp)
        return result

    def remove_deployment(
        self,
        deployment_id: str,
        *,
        function_id: str,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:

        url = self._url(
            f"/function/deployments/remove/{quote(deployment_id, safe='')}")
        resp = self.session.delete(
            url, json={"function_id": function_id}, timeout=self.timeout, headers=self._headers(extra_headers)
        )
        self._raise_for_status(resp)
        return self._safe_json(resp)

    def call_function_as_job(
        self,
        executor_id: str,
        *,
        function_id: str,
        inputs: Dict[str, Any],
        job_name: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
        node_selector: Optional[Dict[str, Any]] = None,
        poll_interval: Optional[int] = None,
        max_retries: Optional[int] = None,
        endpoint: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:

        url = self._url(f"/function/call_as_job/{quote(executor_id, safe='')}")
        payload: Dict[str, Any] = {
            "function_id": function_id,
            "inputs": inputs,
        }
        if job_name is not None:
            payload["job_name"] = job_name
        if parameters is not None:
            payload["parameters"] = parameters
        if node_selector is not None:
            payload["node_selector"] = node_selector
        if poll_interval is not None:
            payload["poll_interval"] = int(poll_interval)
        if max_retries is not None:
            payload["max_retries"] = int(max_retries)
        if endpoint is not None:
            payload["endpoint"] = endpoint

        resp = self.session.post(
            url, json=payload, timeout=self.timeout, headers=self._headers(
                extra_headers)
        )
        self._raise_for_status(resp)
        result = self._safe_json(resp)
        return result.get("job_output_data", result)

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _headers(self, extra: Optional[Dict[str, str]]) -> Dict[str, str]:
        if not extra:
            return self.default_headers
        merged = dict(self.default_headers)
        merged.update(extra)
        return merged

    @staticmethod
    def _raise_for_status(resp: requests.Response) -> None:
        try:
            print(resp.text)
            resp.raise_for_status()
        except requests.HTTPError as e:
            # Attach server body for easier debugging
            body = None
            try:
                body = resp.text
            except Exception:
                pass
            raise requests.HTTPError(f"{e} | body={body}") from e

    @staticmethod
    def _safe_json(resp: requests.Response) -> Dict[str, Any]:
        try:
            data = resp.json()
            if isinstance(data, dict):
                return data
            return {"data": data}
        except Exception:
            return {"text": resp.text}
