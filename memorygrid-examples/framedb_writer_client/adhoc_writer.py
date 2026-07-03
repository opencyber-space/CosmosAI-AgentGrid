import os
import uuid
import logging
from typing import Optional, Dict, Any

from .interfaces.memory import RedisInterface
from .interfaces.storage import TiDBInterface
from .routing import ObjectRoutingClient, StreamRoutingClient
from .cluster_info import FrameDBClusterClient

logger = logging.getLogger("FrameDBWriter")


def _with_scheme(url: str, scheme: str) -> str:
    if "://" not in url:
        return f"{scheme}://{url}"
    return url


class FrameDBWriter:
    def __init__(
        self,
        cluster_client: FrameDBClusterClient,
        object_routing_client: Optional[ObjectRoutingClient] = None,
        stream_routing_client: Optional[StreamRoutingClient] = None,
    ):
        self.cluster_client = cluster_client
        self.object_routing_client = object_routing_client
        self.stream_routing_client = stream_routing_client

    def write(
        self,
        key: Optional[str],
        framedb_id: str,
        data: bytes,
        type_: str,
        metadata: Optional[Dict[str, Any]] = None,
        update_routing: bool = True
    ) -> Dict[str, Any]:
        if not key:
            key = str(uuid.uuid4())
            logger.info(f"Generated UUID key: {key}")

        # Step 1: Get instance config
        try:
            if type_ == "storage":
                resp = self.cluster_client.get_persistent_instance_by_id(framedb_id)
            elif type_ in ("in-memory", "stream"):
                resp = self.cluster_client.get_instance_by_id(framedb_id)
            else:
                raise ValueError(f"Unsupported FrameDB type: {type_}")

            if not resp["success"]:
                return {"success": False, "message": f"Instance not found: {resp['error']}"}

            instance = resp["data"]
            public_url = instance["public_url"]
            # cluster_id = instance["cluster_id"]
            # logger.info(f"Resolved public URL for FrameDB {framedb_id} in cluster {cluster_id}")
        except Exception as e:
            logger.error(f"Error resolving FrameDB config: {e}")
            return {"success": False, "message": f"Config resolution failed: {e}"}

        # Step 2: Perform the actual write
        try:
            if type_ == "in-memory":
                redis = RedisInterface(_with_scheme(public_url, "redis"))
                redis.connect()
                redis.set(key, data)
            elif type_ == "storage":
                tidb = TiDBInterface(_with_scheme(public_url, "mysql"))
                tidb.connect()
                tidb.set(key, data)
            elif type_ == "stream":
                redis = RedisInterface(_with_scheme(public_url, "redis"))
                redis.connect()
                redis.lpush(key, data)
        except Exception as e:
            logger.error(f"Write failed for key {key}: {e}")
            return {"success": False, "message": f"Write failed: {e}"}

        # Step 3: Optionally update routing
        if update_routing:
            try:
                if type_ == "stream":
                    if not self.stream_routing_client:
                        raise RuntimeError("StreamRoutingClient not configured")
                    status, result = self.stream_routing_client.register_stream(
                        queue_name=key,
                        framedb_id=framedb_id,
                        metadata=metadata or {}
                    )
                else:
                    if not self.object_routing_client:
                        raise RuntimeError("ObjectRoutingClient not configured")
                    status, result = self.object_routing_client.create_object(
                        object_id=key,
                        framedb_id=framedb_id,
                        framedb_type=type_,
                        size=len(data),
                        metadata=metadata or {}
                    )
                if status != 200 or not result.get("success"):
                    logger.warning(f"Routing update failed for key {key}: {result}")
            except Exception as e:
                logger.error(f"Routing update exception: {e}")

        return {"success": True, "message": "Write successful", "key": key}

def new_framedb_writer(routing_service_url: str, config_service_url: str):

    routing_client = ObjectRoutingClient(routing_service_url)
    stream_client = StreamRoutingClient(routing_service_url)

    config_client = FrameDBClusterClient(config_service_url)

    return FrameDBWriter(config_client, routing_client, stream_client)
