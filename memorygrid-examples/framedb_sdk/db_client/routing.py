import requests
from typing import List, Dict, Optional, Any
import logging

logger = logging.getLogger(__name__)


class ObjectRoutingClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def create_object(self, object_id: str, framedb_id: str, framedb_type: str,
                      copies: Optional[List[Dict[str, str]]] = None,
                      size: Optional[int] = None,
                      metadata: Optional[Dict[str, Any]] = None):
        url = f"{self.base_url}/framedb/objects"
        payload = {
            "object_id": object_id,
            "framedb_id": framedb_id,
            "framedb_type": framedb_type,
            "copies": copies or [],
            "size": size,
            "metadata": metadata or {}
        }
        resp = requests.post(url, json=payload)
        return resp.status_code, resp.json()

    def update_object(self, object_id: str, update_fields: Dict[str, Any]):
        url = f"{self.base_url}/framedb/objects/{object_id}/update"
        resp = requests.post(url, json=update_fields)
        return resp.status_code, resp.json()

    def delete_object(self, object_id: str):
        url = f"{self.base_url}/framedb/objects/{object_id}"
        resp = requests.delete(url)
        return resp.status_code, resp.json()

    def get_object(self, object_id: str):
        url = f"{self.base_url}/framedb/objects/{object_id}"
        resp = requests.get(url)
        return resp.status_code, resp.json()

    def query_objects(self, filters: Optional[Dict[str, Any]] = None):
        url = f"{self.base_url}/framedb/objects"
        resp = requests.get(url, json=filters or {})
        return resp.status_code, resp.json()

    def add_copy(self, object_id: str, framedb_id: str, framedb_type: str):
        url = f"{self.base_url}/framedb/objects/{object_id}/add-copy"
        payload = {
            "framedb_id": framedb_id,
            "framedb_type": framedb_type
        }
        resp = requests.post(url, json=payload)
        return resp.status_code, resp.json()

    def remove_copy(self, object_id: str, framedb_id: str):
        url = f"{self.base_url}/framedb/objects/{object_id}/remove-copy"
        payload = {"framedb_id": framedb_id}
        resp = requests.post(url, json=payload)
        return resp.status_code, resp.json()

    def copy_exists(self, object_id: str, framedb_id: str):
        url = f"{self.base_url}/framedb/objects/{object_id}/copy-exists/{framedb_id}"
        resp = requests.get(url)
        return resp.status_code, resp.json()


class StreamRoutingClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def register_stream(self, queue_name: str, framedb_id: str,
                        metadata: Optional[Dict[str, Any]] = None):
        url = f"{self.base_url}/framedb/streams"
        payload = {
            "queue_name": queue_name,
            "framedb_id": framedb_id,
            "metadata": metadata or {}
        }
        resp = requests.post(url, json=payload)
        return resp.status_code, resp.json()

    def update_stream(self, queue_name: str, update_fields: Dict[str, Any]):
        url = f"{self.base_url}/framedb/streams/{queue_name}/update"
        resp = requests.post(url, json=update_fields)
        return resp.status_code, resp.json()

    def delete_stream(self, queue_name: str):
        url = f"{self.base_url}/framedb/streams/{queue_name}"
        resp = requests.delete(url)
        return resp.status_code, resp.json()

    def get_stream(self, queue_name: str):
        url = f"{self.base_url}/framedb/streams/{queue_name}"
        resp = requests.get(url)
        return resp.status_code, resp.json()

    def query_streams(self, filters: Optional[Dict[str, Any]] = None):
        url = f"{self.base_url}/framedb/streams"
        resp = requests.get(url, json=filters or {})
        return resp.status_code, resp.json()
