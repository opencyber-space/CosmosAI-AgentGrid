from abc import ABC, abstractmethod
from typing import List, Optional

from ..backends.arango_client import ArangoBackend
from ..backends.weaviate_client import WeaviateClient
from ..backends.postgres_client import PostgresClient
from ..config import MemoryConfig
from ..embeddings import EmbeddingProvider
from ..models import BaseMemory


class BaseMemoryStore(ABC):
    def __init__(
        self,
        weaviate: WeaviateClient,
        arango: ArangoBackend,
        postgres: PostgresClient,
        embedder: EmbeddingProvider,
        config: MemoryConfig,
    ):
        self.weaviate = weaviate
        self.arango = arango
        self.postgres = postgres
        self.embedder = embedder
        self.config = config

    @abstractmethod
    def store(self, memory: BaseMemory) -> str:
        """Persist a memory across all three backends. Returns the memory ID."""

    @abstractmethod
    def retrieve(self, memory_id: str) -> Optional[BaseMemory]:
        """Fetch a memory by exact ID."""

    @abstractmethod
    def search(self, query: str, top_k: int = 5) -> List[BaseMemory]:
        """Return up to top_k memories ranked by semantic similarity to query."""

    @abstractmethod
    def update(self, memory: BaseMemory) -> None:
        """Overwrite an existing memory in all backends."""

    @abstractmethod
    def delete(self, memory_id: str) -> None:
        """Remove a memory from all backends."""

    def _embed(self, text: str) -> List[float]:
        return self.embedder.embed(text)
