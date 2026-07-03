import grpc
import uuid
import logging
from typing import Optional, Dict

from . import framedb_pb2
from . import framedb_pb2_grpc

logger = logging.getLogger("ObjectsAPI")
logger.setLevel(logging.INFO)


class ObjectsAPI:
    def __init__(self, grpc_address: str):
        try:
            self.channel = grpc.insecure_channel(grpc_address)
            self.stub = framedb_pb2_grpc.ObjectServiceStub(self.channel)
            logger.info(f"Connected to ObjectService at {grpc_address}")
        except Exception as e:
            logger.error(f"Failed to connect to gRPC service: {e}")
            raise

    def _build_object(
        self,
        framedb_id: str,
        data: bytes,
        type_: str,
        key: Optional[str] = None,
        metadata: Optional[Dict] = None
    ) -> framedb_pb2.Object:
        if not key:
            key = str(uuid.uuid4())
            logger.info(f"Generated UUID key: {key} for type: {type_}")
        return framedb_pb2.Object(
            key=key,
            framedb_id=framedb_id,
            data=data,
            metadata=(metadata or {}).__str__(),
            type=type_
        )

    def _write_object(self, obj: framedb_pb2.Object) -> framedb_pb2.SetObjectResponse:
        try:
            request = framedb_pb2.SetObjectRequest(object=obj)
            response = self.stub.SetObject(request)
            logger.info(f"SetObject success={response.success}, key={obj.key}, type={obj.type}")
            return response
        except grpc.RpcError as e:
            logger.error(f"gRPC error during SetObject: {e.code()} - {e.details()}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in SetObject: {e}")
            raise

    def write_to_memory(
        self,
        framedb_id: str,
        data: bytes,
        key: Optional[str] = None,
        metadata: Optional[Dict] = None
    ) -> framedb_pb2.SetObjectResponse:
        obj = self._build_object(framedb_id, data, "in-memory", key, metadata)
        return self._write_object(obj)

    def write_to_persistent(
        self,
        framedb_id: str,
        data: bytes,
        key: Optional[str] = None,
        metadata: Optional[Dict] = None
    ) -> framedb_pb2.SetObjectResponse:
        obj = self._build_object(framedb_id, data, "storage", key, metadata)
        return self._write_object(obj)

    def write_to_stream(
        self,
        framedb_id: str,
        data: bytes,
        key: Optional[str] = None,
        metadata: Optional[Dict] = None
    ) -> framedb_pb2.SetObjectResponse:
        obj = self._build_object(framedb_id, data, "stream", key, metadata)
        return self._write_object(obj)


def new_objects_api_client(writer_address: str):
    return ObjectsAPI(writer_address)