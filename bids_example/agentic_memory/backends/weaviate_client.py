from typing import List, Tuple

import weaviate
from weaviate.classes.config import Configure, DataType, Property, VectorDistances
from weaviate.classes.query import MetadataQuery

from ..config import WeaviateConfig

MEMORY_TYPES = ["episodic", "semantic", "procedural", "reflective", "reward"]


class WeaviateClient:
    def __init__(self, config: WeaviateConfig):
        self.config = config
        self._client = weaviate.connect_to_local(
            host=config.host,
            port=config.port,
            grpc_port=config.grpc_port,
        )
        self._ensure_all_collections()

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def disconnect(self):
        self._client.close()

    # ------------------------------------------------------------------
    # Collection lifecycle
    # ------------------------------------------------------------------

    def _collection_name(self, memory_type: str) -> str:
        return f"{self.config.collection_prefix}{memory_type.capitalize()}"

    def _ensure_collection(self, name: str):
        if not self._client.collections.exists(name):
            self._client.collections.create(
                name=name,
                vectorizer_config=Configure.Vectorizer.none(),
                vector_index_config=Configure.VectorIndex.hnsw(
                    distance_metric=VectorDistances.COSINE
                ),
                properties=[
                    Property(name="memory_id", data_type=DataType.TEXT)
                ],
            )

    def _ensure_all_collections(self):
        for mt in MEMORY_TYPES:
            self._ensure_collection(self._collection_name(mt))

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def insert(self, memory_type: str, memory_id: str, embedding: List[float]):
        collection = self._client.collections.get(self._collection_name(memory_type))
        collection.data.insert(
            properties={"memory_id": memory_id},
            vector=embedding,
            uuid=memory_id,
        )

    def search(self, memory_type: str, embedding: List[float], top_k: int = 5) -> List[Tuple[str, float]]:
        collection = self._client.collections.get(self._collection_name(memory_type))
        response = collection.query.near_vector(
            near_vector=embedding,
            limit=top_k,
            return_metadata=MetadataQuery(distance=True),
        )
        return [
            (obj.properties["memory_id"], 1.0 - (obj.metadata.distance or 0.0))
            for obj in response.objects
        ]

    def delete(self, memory_type: str, memory_id: str):
        collection = self._client.collections.get(self._collection_name(memory_type))
        collection.data.delete_by_id(memory_id)

    def update(self, memory_type: str, memory_id: str, embedding: List[float]):
        self.delete(memory_type, memory_id)
        self.insert(memory_type, memory_id, embedding)
