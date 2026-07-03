import os
import logging
from typing import Dict, Any, List, Optional
from cachetools import LFUCache
import pickle
from abc import ABC, abstractmethod
import boto3


from .interfaces.memory import RedisInterface
from .interfaces.storage import TiDBInterface
from .db_client.cluster_info import FrameDBClusterClient
from .db_client.routing import ObjectRoutingClient
from .db_client.routing import StreamRoutingClient
from .cache import LFUCache as FramesCache


logger = logging.getLogger(__name__)

class PickleSerializer:
    def serialize(self, data) -> bytes:
        return pickle.dumps(data)

    def deserialize(self, data: bytes):
        return pickle.loads(data)


class ObjectStorageBackend(ABC):
    @abstractmethod
    def upload(self, key: str, data: bytes):
        pass

    @abstractmethod
    def download(self, key: str) -> bytes:
        pass


class S3ObjectStorageBackend(ObjectStorageBackend):
    def __init__(self, config: Dict[str, Any]):
        self.bucket = config["bucket"]
        self.client = boto3.client(
            "s3",
            aws_access_key_id=config["access_key"],
            aws_secret_access_key=config["secret_key"],
            region_name=config.get("region")
        )

    def upload(self, key: str, data: bytes):
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data)

    def download(self, key: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        return response["Body"].read()

def _ensure_url_scheme(url: str, valid_schemes: List[str], default_scheme: str) -> str:
    if any(url.startswith(f"{scheme}://") for scheme in valid_schemes):
        return url
    return f"{default_scheme}://{url}"


# Default cache size fallback
def get_cached_connection(connection_cache: LFUCache, framedb_id: str, url: str, kind: str):
    if framedb_id in connection_cache:
        return connection_cache[framedb_id]

    if kind == "in-memory" or kind == "stream":
        url = _ensure_url_scheme(url, ["redis", "rediss", "unix"], "redis")
        conn = RedisInterface(url)
    elif kind == "storage":
        url = _ensure_url_scheme(url, ["mysql", "mysql+pymysql"], "mysql")
        conn = TiDBInterface(url)
    else:
        raise ValueError(f"Unsupported connection type: {kind}")

    conn.connect()
    connection_cache[framedb_id] = conn
    return conn

def get_object(
    object_id: str,
    cluster_client: FrameDBClusterClient,
    routing_client: ObjectRoutingClient,
    stream_routing_client: StreamRoutingClient,
    global_cache: FramesCache,
    connections_cache: LFUCache
) -> Dict[str, Any]:
    current_cluster = os.getenv("CLUSTER_ID")

    # Step 0: Try LFU cache
    cached = global_cache.get(object_id)
    if cached:
        cached_meta = global_cache.get_metadata(object_id)
        return {
            "found": True,
            "object": {
                "key": object_id,
                "data": cached,
                "metadata": cached_meta.get("metadata", {}),
                "framedb_id": cached_meta.get("framedb_id"),
                "type": cached_meta.get("type", "cache")
            },
            "message": "Object served from cache"
        }

    # Step 1: Routing lookup
    try:
        status, route_info = routing_client.get_object(object_id)
        if status != 200 or not route_info.get("success"):
            # fallback to stream lookup
            status, route_info = stream_routing_client.get_stream(object_id)
            if status != 200 or not route_info.get("success"):
                return {"found": False, "message": f"Object/stream '{object_id}' not found in routing service"}
            metadata = route_info["data"]
            framedb_type = "stream"
        else:
            metadata = route_info["data"]
            framedb_type = metadata.get("framedb_type")
    except Exception as e:
        logger.error(f"Routing lookup failed: {e}")
        return {"found": False, "message": f"Routing lookup failed: {e}"}

    framedb_id = metadata.get("framedb_id")
    copies = metadata.get("copies", [])

    # Step 2: Choose best copy
    selected_framedb_id = framedb_id
    for copy in copies:
        if copy.get("cluster_id") == current_cluster:
            selected_framedb_id = copy.get("framedb_id")
            break

    # Step 3: Resolve instance
    try:
        response = cluster_client.get_instance_by_id(selected_framedb_id) \
            if framedb_type in ("in-memory", "stream") \
            else cluster_client.get_persistent_instance_by_id(selected_framedb_id)

        if not response["success"]:
            return {"found": False, "message": f"FrameDB instance not found: {response['error']}"}
    except Exception as e:
        logger.error(f"Error fetching instance info: {e}")
        return {"found": False, "message": f"Failed to fetch instance info: {e}"}

    instance = response["data"]
    url = instance["local_url"] if instance.get("cluster_id", "") == current_cluster else instance["public_url"]

    # Step 4: Read data
    try:
        if framedb_type == "in-memory":
            redis = get_cached_connection(connections_cache, selected_framedb_id, url, "in-memory")
            redis.connect()
            data = redis.get(object_id)
        elif framedb_type == "storage":
            tidb = get_cached_connection(connections_cache, selected_framedb_id, url, "storage")
            tidb.connect()
            data = tidb.get(object_id)
        elif framedb_type == "stream":
            redis = get_cached_connection(connections_cache, selected_framedb_id, url, "stream")
            redis.connect()
            data = redis.rpop(object_id)
    except Exception as e:
        logger.error(f"Data read failed: {e}")
        return {"found": False, "message": f"Data read failed: {e}"}

    if data is None:
        return {"found": False, "message": f"No data found for key '{object_id}'"}

    # Add to cache
    try:
        global_cache.add(object_id, data, metadata={
            "metadata": metadata.get("metadata", {}),
            "framedb_id": selected_framedb_id,
            "type": framedb_type
        })
    except Exception as e:
        logger.warning(f"Cache insert failed for '{object_id}': {e}")

    return {
        "found": True,
        "object": {
            "key": object_id,
            "data": data,
            "metadata": metadata.get("metadata", {}),
            "framedb_id": selected_framedb_id,
            "type": framedb_type
        },
        "message": "Object retrieved successfully"
    }


def set_object(
    obj: Dict[str, Any],
    cluster_client: FrameDBClusterClient,
    object_routing_client: ObjectRoutingClient,
    stream_routing_client: StreamRoutingClient,
    global_cache: FramesCache,
    connections_cache: LFUCache
) -> Dict[str, Any]:
    framedb_id = obj["framedb_id"]
    storage_type = obj["type"]
    cluster_id = os.getenv("CLUSTER_ID")

    # Step 1: Get instance info
    if storage_type == "in-memory":
        response = cluster_client.get_instance_by_id(framedb_id)
    elif storage_type == "storage":
        response = cluster_client.get_persistent_instance_by_id(framedb_id)
    elif storage_type == "stream":
        response = cluster_client.get_instance_by_id(framedb_id)
    else:
        return {"success": False, "message": f"Unsupported type: {storage_type}"}

    if not response["success"]:
        return {"success": False, "message": f"FrameDB instance not found: {response['error']}"}

    instance = response["data"]
    instance_cluster_id = instance.get("cluster_id", "")
    url = instance["local_url"] if instance_cluster_id == cluster_id else instance["public_url"]

    # Step 2: Write data
    try:
        if storage_type == "in-memory":
            redis = get_cached_connection(connections_cache, framedb_id, url, "in-memory")
            redis.connect()
            redis.set(obj["key"], obj["data"])

        elif storage_type == "storage":
            tidb = get_cached_connection(connections_cache, framedb_id, url, "storage")
            tidb.connect()
            tidb.set(obj["key"], obj["data"])

        elif storage_type == "stream":
            redis = get_cached_connection(connections_cache, framedb_id, url, "stream")
            redis.connect()
            redis.lpush(obj["key"], obj["data"])

        # Step 2b: Add to cache
        try:
            global_cache.add(obj["key"], obj["data"], metadata={
                "metadata": obj.get("metadata", {}),
                "framedb_id": framedb_id,
                "type": storage_type
            })
        except Exception as e:
            logger.warning(f"LFU cache insert failed for key {obj['key']}: {e}")

    except Exception as e:
        logger.error(f"Write failed for key {obj['key']}: {e}")
        return {"success": False, "message": f"Write failed: {e}"}

    # Step 3: Register in routing
    try:
        if storage_type == "stream":
            status, result = stream_routing_client.register_stream(
                queue_name=obj["key"],
                framedb_id=framedb_id,
                metadata=obj.get("metadata", {})
            )
        else:
            status, result = object_routing_client.create_object(
                object_id=obj["key"],
                framedb_id=framedb_id,
                framedb_type=storage_type,
                size=len(obj["data"]),
                metadata=obj.get("metadata", {})
            )

        if status in (200, 201) and result.get("success"):
            return {"success": True, "message": "Object stored and routed successfully"}
        else:
            return {"success": False, "message": f"Routing failed: {result}"}

    except Exception as e:
        logger.error(f"Routing registration failed: {e}")
        return {"success": False, "message": f"Routing registration failed: {e}"}

def create_backup(
    object_id: str,
    target_framedb_id: str,
    cluster_client: FrameDBClusterClient,
    object_routing_client: ObjectRoutingClient,
    stream_routing_client: StreamRoutingClient,
    global_cache: FramesCache,
    connections_cache: LFUCache
) -> Dict[str, Any]:
    # Step 1: Fetch object from source
    response = get_object(
        object_id=object_id,
        cluster_client=cluster_client,
        routing_client=object_routing_client,
        stream_routing_client=stream_routing_client,
        global_cache=global_cache,
        connections_cache=connections_cache
    )

    if not response.get("found"):
        return {"success": False, "message": f"Source object not found: {response.get('message')}"}

    obj = response["object"]
    backup_obj = {
        "key": obj["key"],
        "data": obj["data"],
        "metadata": obj.get("metadata", {}),
        "framedb_id": target_framedb_id,
        "type": obj["type"]
    }

    # Step 2: Write to target FrameDB
    return set_object(
        obj=backup_obj,
        cluster_client=cluster_client,
        object_routing_client=object_routing_client,
        stream_routing_client=stream_routing_client,
        global_cache=global_cache,
        connections_cache=connections_cache
    )


def create_bulk_backup(
    keys: list,
    target_framedb_id: str,
    cluster_client: FrameDBClusterClient,
    object_routing_client: ObjectRoutingClient,
    stream_routing_client: StreamRoutingClient,
    global_cache: FramesCache,
    connections_cache: LFUCache
) -> Dict[str, Any]:
    results = {}
    for key in keys:
        result = create_backup(
            object_id=key,
            target_framedb_id=target_framedb_id,
            cluster_client=cluster_client,
            object_routing_client=object_routing_client,
            stream_routing_client=stream_routing_client,
            global_cache=global_cache,
            connections_cache=connections_cache
        )
        results[key] = result

    success_count = sum(1 for r in results.values() if r.get("success"))
    return {
        "success": True,
        "summary": f"Backed up {success_count}/{len(keys)} objects",
        "results": results
    }


def listen_for_stream_data(
    queue_name: str,
    framedb_id: str,
    cluster_client: FrameDBClusterClient,
    connections_cache: LFUCache
):
    try:
        response = cluster_client.get_instance_by_id(framedb_id)
        if not response["success"]:
            logger.error(f"Failed to fetch instance '{framedb_id}': {response['error']}")
            return

        instance = response["data"]
        current_cluster = os.getenv("CLUSTER_ID")
        url = instance["local_url"] if instance.get("cluster_id", "") == current_cluster else instance["public_url"]

        redis = get_cached_connection(connections_cache, framedb_id, url, "stream")
        return redis.listen_for_inputs(queue_name)

    except Exception as e:
        logger.error(f"Error preparing to listen on stream '{queue_name}': {e}")
        return iter([])  


def bulk_read(
    keys: List[str],
    framedb_id: str,
    cluster_client: FrameDBClusterClient,
    connections_cache: LFUCache
) -> Dict[str, bytes]:
    try:
        response = cluster_client.get_persistent_instance_by_id(framedb_id)
        if not response["success"]:
            logger.error(f"Failed to fetch persistent instance '{framedb_id}': {response['error']}")
            return {}

        instance = response["data"]
        current_cluster = os.getenv("CLUSTER_ID")
        url = instance["local_url"] if instance.get("cluster_id", "") == current_cluster else instance["public_url"]

        tidb = get_cached_connection(connections_cache, framedb_id, url, "storage")
        return tidb.bulk_read(keys)

    except Exception as e:
        logger.error(f"Bulk read failed for FrameDB '{framedb_id}': {e}")
        return {}


def pull_all_stream_data(
    queue_name: str,
    framedb_id: str,
    cluster_client: FrameDBClusterClient,
    connections_cache: LFUCache
):
    try:
        response = cluster_client.get_instance_by_id(framedb_id)
        if not response["success"]:
            logger.error(f"Failed to fetch instance '{framedb_id}': {response['error']}")
            return

        instance = response["data"]
        current_cluster = os.getenv("CLUSTER_ID")
        url = instance["local_url"] if instance.get("cluster_id", "") == current_cluster else instance["public_url"]

        redis = get_cached_connection(connections_cache, framedb_id, url, "stream")
        return redis.pull_all_inputs(queue_name)

    except Exception as e:
        logger.error(f"Error pulling from stream '{queue_name}': {e}")
        return iter([])  # return empty generator on error


def set_pythonic_object(
    key: str,
    obj: Any,
    framedb_id: str,
    framedb_type: str,
    cluster_client: FrameDBClusterClient,
    object_routing_client: ObjectRoutingClient,
    stream_routing_client: StreamRoutingClient,
    global_cache: FramesCache,
    connections_cache: LFUCache,
    serializer: Optional[Any] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    serializer = serializer or PickleSerializer()

    try:
        serialized_data = serializer.serialize(obj)
    except Exception as e:
        logger.error(f"Serialization failed for key '{key}': {e}")
        return {"success": False, "message": f"Serialization error: {e}"}

    return set_object(
        obj={
            "key": key,
            "data": serialized_data,
            "metadata": metadata or {},
            "framedb_id": framedb_id,
            "type": framedb_type
        },
        cluster_client=cluster_client,
        object_routing_client=object_routing_client,
        stream_routing_client=stream_routing_client,
        global_cache=global_cache,
        connections_cache=connections_cache
    )


def get_pythonic_object(
    key: str,
    cluster_client: FrameDBClusterClient,
    object_routing_client: ObjectRoutingClient,
    stream_routing_client: StreamRoutingClient,
    global_cache: FramesCache,
    connections_cache: LFUCache,
    deserializer: Optional[Any] = None
) -> Dict[str, Any]:
    deserializer = deserializer or PickleSerializer()

    response = get_object(
        object_id=key,
        cluster_client=cluster_client,
        routing_client=object_routing_client,
        stream_routing_client=stream_routing_client,
        global_cache=global_cache,
        connections_cache=connections_cache
    )

    if not response.get("found"):
        return {"found": False, "message": response.get("message")}

    try:
        raw_data = response["object"]["data"]
        response["object"]["python_object"] = deserializer.deserialize(raw_data)
    except Exception as e:
        logger.error(f"Deserialization failed for key '{key}': {e}")
        return {"found": False, "message": f"Deserialization failed: {e}"}

    return response


def backup_to_object_storage(
    keys: list,
    framedb_id: str,
    cluster_client: FrameDBClusterClient,
    object_routing_client: ObjectRoutingClient,
    stream_routing_client: StreamRoutingClient,
    global_cache: FramesCache,
    connections_cache: LFUCache,
    s3_credentials_dict: Optional[Dict[str, str]] = None,
    custom_backup_storage_backend: Optional[ObjectStorageBackend] = None
) -> Dict[str, Any]:

    backend = custom_backup_storage_backend or S3ObjectStorageBackend(s3_credentials_dict)
    results = {}

    for key in keys:
        obj_resp = get_object(
            object_id=key,
            cluster_client=cluster_client,
            routing_client=object_routing_client,
            stream_routing_client=stream_routing_client,
            global_cache=global_cache,
            connections_cache=connections_cache
        )

        if obj_resp.get("found"):
            try:
                data = obj_resp["object"]["data"]
                backend.upload(key, data)
                results[key] = {"success": True}
            except Exception as e:
                logger.error(f"Failed to upload backup for '{key}': {e}")
                results[key] = {"success": False, "error": str(e)}
        else:
            results[key] = {"success": False, "error": obj_resp.get("message")}

    return {
        "success": True,
        "results": results
    }


def restore_from_backup(
    keys: list,
    framedb_id: str,
    framedb_type: str,
    cluster_client: FrameDBClusterClient,
    object_routing_client: ObjectRoutingClient,
    stream_routing_client: StreamRoutingClient,
    global_cache: FramesCache,
    connections_cache: LFUCache,
    s3_credentials_dict: Optional[Dict[str, str]] = None,
    custom_backup_storage_backend: Optional[ObjectStorageBackend] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:

    backend = custom_backup_storage_backend or S3ObjectStorageBackend(s3_credentials_dict)
    results = {}

    for key in keys:
        try:
            data = backend.download(key)
            result = set_object(
                obj={
                    "key": key,
                    "data": data,
                    "metadata": metadata or {},
                    "framedb_id": framedb_id,
                    "type": framedb_type
                },
                cluster_client=cluster_client,
                object_routing_client=object_routing_client,
                stream_routing_client=stream_routing_client,
                global_cache=global_cache,
                connections_cache=connections_cache
            )
            results[key] = result
        except Exception as e:
            logger.error(f"Failed to restore key '{key}': {e}")
            results[key] = {"success": False, "error": str(e)}

    return {
        "success": True,
        "results": results
    }


class FrameDBClient:
    def __init__(
        self,
        cluster_url: str,
        routing_url: str,
        cache_size_bytes: int = 100 * 1024 * 1024,
        connection_cache_size: int = 100
    ):
        # DB clients
        self.cluster_client = FrameDBClusterClient(cluster_url)
        self.object_routing_client = ObjectRoutingClient(routing_url)
        self.stream_routing_client = StreamRoutingClient(routing_url)

        # Caches
        self.global_cache = FramesCache(max_size_bytes=cache_size_bytes)
        self.connections_cache = LFUCache(maxsize=connection_cache_size)

    def set_object(self, obj: dict):
        return set_object(
            obj,
            self.cluster_client,
            self.object_routing_client,
            self.stream_routing_client,
            self.global_cache,
            self.connections_cache
        )

    def get_object(self, object_id: str):
        return get_object(
            object_id,
            self.cluster_client,
            self.object_routing_client,
            self.stream_routing_client,
            self.global_cache,
            self.connections_cache
        )

    def create_backup(self, object_id: str, target_framedb_id: str):
        return create_backup(
            object_id,
            target_framedb_id,
            self.cluster_client,
            self.object_routing_client,
            self.stream_routing_client,
            self.global_cache,
            self.connections_cache
        )

    def create_bulk_backup(self, keys: list, target_framedb_id: str):
        return create_bulk_backup(
            keys,
            target_framedb_id,
            self.cluster_client,
            self.object_routing_client,
            self.stream_routing_client,
            self.global_cache,
            self.connections_cache
        )

    def listen_for_stream_data(self, queue_name: str, framedb_id: str):
        return listen_for_stream_data(
            queue_name,
            framedb_id,
            self.cluster_client,
            self.connections_cache
        )

    def pull_all_stream_data(self, queue_name: str, framedb_id: str):
        return pull_all_stream_data(
            queue_name,
            framedb_id,
            self.cluster_client,
            self.connections_cache
        )

    def set_pythonic_object(self, key, obj, framedb_id, framedb_type, serializer=None, metadata=None):
        return set_pythonic_object(
            key,
            obj,
            framedb_id,
            framedb_type,
            self.cluster_client,
            self.object_routing_client,
            self.stream_routing_client,
            self.global_cache,
            self.connections_cache,
            serializer=serializer,
            metadata=metadata
        )

    def get_pythonic_object(self, key, deserializer=None):
        return get_pythonic_object(
            key,
            self.cluster_client,
            self.object_routing_client,
            self.stream_routing_client,
            self.global_cache,
            self.connections_cache,
            deserializer=deserializer
        )

    def backup_to_object_storage(self, keys, framedb_id, s3_credentials_dict=None, custom_backup_storage_backend=None):
        return backup_to_object_storage(
            keys,
            framedb_id,
            self.cluster_client,
            self.object_routing_client,
            self.stream_routing_client,
            self.global_cache,
            self.connections_cache,
            s3_credentials_dict=s3_credentials_dict,
            custom_backup_storage_backend=custom_backup_storage_backend
        )

    def restore_from_backup(self, keys, framedb_id, framedb_type, s3_credentials_dict=None, custom_backup_storage_backend=None, metadata=None):
        return restore_from_backup(
            keys,
            framedb_id,
            framedb_type,
            self.cluster_client,
            self.object_routing_client,
            self.stream_routing_client,
            self.global_cache,
            self.connections_cache,
            s3_credentials_dict=s3_credentials_dict,
            custom_backup_storage_backend=custom_backup_storage_backend,
            metadata=metadata
        )