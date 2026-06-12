import logging
from typing import Optional, Dict, Any, List, Tuple
from urllib.parse import quote

import requests

from .schema import FunctionEntry

logger = logging.getLogger("FunctionsRegistryClient")
logger.setLevel(logging.INFO)


class FunctionsRegistryClient:
   
    def __init__(
        self,
        base_url: str,
        *,
        timeout: Tuple[int, int] = (5, 30),
        session: Optional[requests.Session] = None,
    ):
       
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def get_function(self, function_id: str) -> Optional[FunctionEntry]:
       
        url = self._url(f"/functions/{function_id}")
        resp = self.session.get(url, timeout=self.timeout)

        if resp.status_code == 404:
            logger.info("Function '%s' not found.", function_id)
            return None

        resp.raise_for_status()
        data = resp.json()
        return FunctionEntry.from_dict(data)

    def query_functions(self, mongo_query: Dict[str, Any]) -> List[FunctionEntry]:
      
        url = self._url("/functions/query/generic")
        resp = self.session.post(url, json=mongo_query, timeout=self.timeout)
        resp.raise_for_status()
        items = resp.json() or []
        return [FunctionEntry.from_dict(doc) for doc in items]

    def get_functions_by_tag(self, tag: str) -> List[FunctionEntry]:
        return self.query_functions({"function_tags": tag})

