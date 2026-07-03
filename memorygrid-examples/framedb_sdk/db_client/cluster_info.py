import requests
import logging

class FrameDBClusterClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')
        self.logger = logging.getLogger("FrameDBClusterClient")

    def get_persistent_instance_by_id(self, framedb_id: str) -> dict:
        try:
            url = f"{self.base_url}/global/framedb/persistent-instances/{framedb_id}"
            response = requests.get(url)
            if response.status_code == 200:
                self.logger.info(f"Fetched persistent instance '{framedb_id}' successfully.")
                return {"success": True, "data": response.json().get("data")}
            else:
                self.logger.warning(f"Failed to fetch persistent instance '{framedb_id}': {response.json().get('error')}")
                return {"success": False, "error": response.json().get("error")}
        except Exception as e:
            self.logger.error(f"Exception in get_persistent_instance_by_id: {e}")
            return {"success": False, "error": str(e)}

    def get_instance_by_id(self, framedb_id: str) -> dict:
        try:
            url = f"{self.base_url}/global/framedb/instances/{framedb_id}"
            response = requests.get(url)
            if response.status_code == 200:
                self.logger.info(f"Fetched in-memory instance '{framedb_id}' successfully.")
                return {"success": True, "data": response.json().get("data")}
            else:
                self.logger.warning(f"Failed to fetch in-memory instance '{framedb_id}': {response.json().get('error')}")
                return {"success": False, "error": response.json().get("error")}
        except Exception as e:
            self.logger.error(f"Exception in get_instance_by_id: {e}")
            return {"success": False, "error": str(e)}
