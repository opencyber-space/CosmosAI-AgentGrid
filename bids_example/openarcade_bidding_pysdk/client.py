import logging
import requests
from typing import Dict, Any, List, Optional
from .exceptions import OpenarcadeError, OpenarcadeNetworkError, OpenarcadeAPIError

class OpenarcadeClient:
    def __init__(self, base_url: str = "http://localhost:5000", log_level: int = logging.WARNING):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        self.logger = logging.getLogger("openarcade_sdk")
        if not self.logger.handlers:
            handler = logging.NullHandler()
            self.logger.addHandler(handler)
        self.logger.setLevel(log_level)
        self.default_log_level = log_level

    def _request(self, method: str, path: str, timeout: Optional[float] = None, log_level: Optional[int] = None, **kwargs) -> Dict[str, Any]:
        url = f"{self.base_url}/{path.lstrip('/')}"
        eff_log_level = log_level if log_level is not None else self.default_log_level
        self.logger.log(eff_log_level, f"Sending {method} request to {url}")
        
        try:
            response = self.session.request(method, url, timeout=timeout, **kwargs)
            self.logger.log(eff_log_level, f"Received response {response.status_code} from {url}")
            if not response.ok:
                try:
                    err_data = response.json()
                except ValueError:
                    err_data = {}
                msg = err_data.get('error', response.text)
                self.logger.error(f"API Error {response.status_code} on {method} {url}: {msg}")
                raise OpenarcadeAPIError(f"API Error: {msg}", status_code=response.status_code, payload=err_data)
        except requests.RequestException as e:
            self.logger.error(f"Network error on {method} {url}: {e}")
            raise OpenarcadeNetworkError(f"Network error: {str(e)}") from e

        try:
            data = response.json()
        except ValueError:
            self.logger.error(f"Non-JSON response from {url}: {response.text}")
            raise OpenarcadeAPIError(f"Invalid JSON response: {response.text}")

        # If the response itself is parsed, we return it as requested by FR-006, 
        # but if HTTP status is severe like 500 without a proper JSON structure, we might want to flag it.
        # Assuming the API always returns a JSON dictionary for success/error.
        if not isinstance(data, dict):
            raise OpenarcadeAPIError(f"Unexpected response structure: {data}")
            
        return data

    # --- Bid Jobs ---

    def create_bid_job(
        self, 
        bid_job_name: Dict[str, str], 
        bid_job_description: Dict[str, Any], 
        bid_job_evaluator_id: str, 
        bid_job_creator_id: str, 
        bid_job_subject_ids: List[str], 
        bid_job_metadata: Optional[Dict[str, Any]] = None,
        bid_job_pqt_id: Optional[str] = None,
        timeout: Optional[float] = None,
        log_level: Optional[int] = None
    ) -> Dict[str, Any]:
        """POST /bid-jobs"""
        payload = {
            "bid_job_name": bid_job_name,
            "bid_job_description": bid_job_description,
            "bid_job_evaluator_id": bid_job_evaluator_id,
            "bid_job_creator_id": bid_job_creator_id,
            "bid_job_subject_ids": bid_job_subject_ids
        }
        if bid_job_metadata is not None:
            payload["bid_job_metadata"] = bid_job_metadata
        if bid_job_pqt_id is not None:
            payload["bid_job_pqt_id"] = bid_job_pqt_id
            
        return self._request("POST", "bid-jobs", json=payload, timeout=timeout, log_level=log_level)

    def get_bid_job(self, bid_job_id: str, timeout: Optional[float] = None, log_level: Optional[int] = None) -> Dict[str, Any]:
        """GET /bid-jobs/{bid_job_id}"""
        return self._request("GET", f"bid-jobs/{bid_job_id}", timeout=timeout, log_level=log_level)

    def update_bid_job(self, bid_job_id: str, updates: Dict[str, Any], timeout: Optional[float] = None, log_level: Optional[int] = None) -> Dict[str, Any]:
        """PATCH /bid-jobs/{bid_job_id}"""
        return self._request("PATCH", f"bid-jobs/{bid_job_id}", json=updates, timeout=timeout, log_level=log_level)

    def delete_bid_job(self, bid_job_id: str, timeout: Optional[float] = None, log_level: Optional[int] = None) -> Dict[str, Any]:
        """DELETE /bid-jobs/{bid_job_id}"""
        return self._request("DELETE", f"bid-jobs/{bid_job_id}", timeout=timeout, log_level=log_level)

    def query_bid_jobs(self, filter_query: Dict[str, Any], timeout: Optional[float] = None, log_level: Optional[int] = None) -> Dict[str, Any]:
        """POST /bid-jobs/query"""
        return self._request("POST", "bid-jobs/query", json=filter_query, timeout=timeout, log_level=log_level)

    # --- Bids ---

    def submit_bid(self, bid_job_id: str, bid_subject_id: str, bid_data: Dict[str, Any], timeout: Optional[float] = None, log_level: Optional[int] = None) -> Dict[str, Any]:
        """POST /bid-jobs/{bid_job_id}/bids"""
        payload = {
            "bid_subject_id": bid_subject_id,
            "bid_data": bid_data
        }
        return self._request("POST", f"bid-jobs/{bid_job_id}/bids", json=payload, timeout=timeout, log_level=log_level)

    def get_job_bids(self, bid_job_id: str, timeout: Optional[float] = None, log_level: Optional[int] = None) -> Dict[str, Any]:
        """GET /bid-jobs/{bid_job_id}/bids"""
        return self._request("GET", f"bid-jobs/{bid_job_id}/bids", timeout=timeout, log_level=log_level)

    def get_bid(self, bid_id: str, timeout: Optional[float] = None, log_level: Optional[int] = None) -> Dict[str, Any]:
        """GET /bids/{bid_id}"""
        return self._request("GET", f"bids/{bid_id}", timeout=timeout, log_level=log_level)

    def update_bid(self, bid_id: str, updates: Dict[str, Any], timeout: Optional[float] = None, log_level: Optional[int] = None) -> Dict[str, Any]:
        """PATCH /bids/{bid_id}"""
        return self._request("PATCH", f"bids/{bid_id}", json=updates, timeout=timeout, log_level=log_level)

    def delete_bid(self, bid_id: str, timeout: Optional[float] = None, log_level: Optional[int] = None) -> Dict[str, Any]:
        """DELETE /bids/{bid_id}"""
        return self._request("DELETE", f"bids/{bid_id}", timeout=timeout, log_level=log_level)

    def query_bids(self, filter_query: Dict[str, Any], timeout: Optional[float] = None, log_level: Optional[int] = None) -> Dict[str, Any]:
        """POST /bids/query"""
        return self._request("POST", "bids/query", json=filter_query, timeout=timeout, log_level=log_level)

    # --- Task Results ---

    def get_job_task_results(self, bid_job_id: str, timeout: Optional[float] = None, log_level: Optional[int] = None) -> Dict[str, Any]:
        """GET /bid-jobs/{bid_job_id}/task-results"""
        return self._request("GET", f"bid-jobs/{bid_job_id}/task-results", timeout=timeout, log_level=log_level)

    def query_task_results(self, filter_query: Dict[str, Any], timeout: Optional[float] = None, log_level: Optional[int] = None) -> Dict[str, Any]:
        """POST /bid-task-results/query"""
        return self._request("POST", "bid-task-results/query", json=filter_query, timeout=timeout, log_level=log_level)
