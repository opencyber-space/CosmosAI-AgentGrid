import hashlib
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from .base import BaseMemoryStore
from ..models import SemanticMemory


class SemanticMemoryStore(BaseMemoryStore):
    """
    Stores factual knowledge as subject–predicate–object triples.

    PostgreSQL — triple lookup, confidence filtering, source tracking.
    Weaviate   — semantic similarity search over the full fact text.
    ArangoDB   — knowledge graph: entity nodes + entity_relations edges,
                 enabling path-finding between concepts.
    """

    # ------------------------------------------------------------------
    # Core CRUD
    # ------------------------------------------------------------------

    def store(self, memory: SemanticMemory) -> str:
        embedding = self._embed(f"{memory.subject} {memory.predicate} {memory.object} {memory.content}")
        memory.embedding = embedding
        if not memory.updated_at:
            memory.updated_at = memory.created_at

        self.postgres.execute(
            """
            INSERT INTO semantic_memories
                (id, subject, predicate, object, confidence, source, content, metadata, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                memory.id, memory.subject, memory.predicate, memory.object,
                memory.confidence, memory.source, memory.content,
                json.dumps(memory.metadata), memory.created_at, memory.updated_at,
            ),
        )

        self.weaviate.insert("semantic", memory.id, embedding)

        self.arango.insert_node("semantic", {
            "_key": memory.id,
            "subject": memory.subject,
            "predicate": memory.predicate,
            "object": memory.object,
            "confidence": memory.confidence,
            "source": memory.source,
        })

        # Maintain entity nodes and a knowledge-graph edge
        self._ensure_entity(memory.subject)
        self._ensure_entity(memory.object)
        try:
            self.arango.insert_edge(
                "entity_relations",
                "entity", _entity_key(memory.subject),
                "entity", _entity_key(memory.object),
                {"predicate": memory.predicate, "memory_id": memory.id, "confidence": memory.confidence},
            )
        except Exception:
            pass  # duplicate edges are acceptable for now

        return memory.id

    def retrieve(self, memory_id: str) -> Optional[SemanticMemory]:
        row = self.postgres.execute_one(
            "SELECT * FROM semantic_memories WHERE id = %s", (memory_id,)
        )
        return self._from_row(row) if row else None

    def search(self, query: str, top_k: int = 5) -> List[SemanticMemory]:
        hits = self.weaviate.search("semantic", self._embed(query), top_k)
        results = []
        for memory_id, score in hits:
            mem = self.retrieve(memory_id)
            if mem:
                mem.score = score
                results.append(mem)
        return results

    def update(self, memory: SemanticMemory) -> None:
        embedding = self._embed(f"{memory.subject} {memory.predicate} {memory.object} {memory.content}")
        memory.embedding = embedding
        memory.updated_at = datetime.utcnow()

        self.postgres.execute(
            """
            UPDATE semantic_memories
            SET subject=%s, predicate=%s, object=%s, confidence=%s, source=%s,
                content=%s, metadata=%s, updated_at=%s
            WHERE id=%s
            """,
            (
                memory.subject, memory.predicate, memory.object,
                memory.confidence, memory.source, memory.content,
                json.dumps(memory.metadata), memory.updated_at, memory.id,
            ),
        )
        self.weaviate.update("semantic", memory.id, embedding)
        self.arango.update_node("semantic", memory.id, {
            "subject": memory.subject,
            "predicate": memory.predicate,
            "object": memory.object,
            "confidence": memory.confidence,
        })

    def delete(self, memory_id: str) -> None:
        self.postgres.execute("DELETE FROM semantic_memories WHERE id = %s", (memory_id,))
        self.weaviate.delete("semantic", memory_id)
        self.arango.delete_node("semantic", memory_id)

    # ------------------------------------------------------------------
    # Triple lookups
    # ------------------------------------------------------------------

    def get_by_subject(self, subject: str) -> List[SemanticMemory]:
        rows = self.postgres.execute(
            "SELECT * FROM semantic_memories WHERE subject = %s ORDER BY confidence DESC",
            (subject,),
        )
        return [self._from_row(r) for r in rows]

    def get_by_predicate(self, predicate: str) -> List[SemanticMemory]:
        rows = self.postgres.execute(
            "SELECT * FROM semantic_memories WHERE predicate = %s ORDER BY confidence DESC",
            (predicate,),
        )
        return [self._from_row(r) for r in rows]

    def get_triple(self, subject: str, predicate: str) -> Optional[SemanticMemory]:
        row = self.postgres.execute_one(
            """SELECT * FROM semantic_memories
               WHERE subject = %s AND predicate = %s
               ORDER BY confidence DESC LIMIT 1""",
            (subject, predicate),
        )
        return self._from_row(row) if row else None

    def get_above_confidence(self, threshold: float = 0.8) -> List[SemanticMemory]:
        rows = self.postgres.execute(
            "SELECT * FROM semantic_memories WHERE confidence >= %s ORDER BY confidence DESC",
            (threshold,),
        )
        return [self._from_row(r) for r in rows]

    # ------------------------------------------------------------------
    # Knowledge-graph traversal
    # ------------------------------------------------------------------

    def find_path(self, from_entity: str, to_entity: str) -> List[Dict[str, Any]]:
        """Shortest path between two entity nodes in the knowledge graph."""
        return self.arango.find_entity_path(
            _entity_key(from_entity), _entity_key(to_entity)
        )

    def get_neighbors(self, entity: str, direction: str = "OUTBOUND") -> List[Dict[str, Any]]:
        """All entities directly connected to this entity."""
        return self.arango.get_related("entity", _entity_key(entity), "entity_relations", direction)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _ensure_entity(self, name: str):
        key = _entity_key(name)
        if not self.arango.get_node("entity", key):
            self.arango.insert_node("entity", {"_key": key, "name": name})

    def _from_row(self, row: Dict[str, Any]) -> SemanticMemory:
        return SemanticMemory(
            id=row["id"],
            content=row["content"],
            subject=row.get("subject") or "",
            predicate=row.get("predicate") or "",
            object=row.get("object") or "",
            confidence=float(row.get("confidence", 1.0)),
            source=row.get("source") or "",
            metadata=row.get("metadata") or {},
            created_at=_to_dt(row.get("created_at")),
            updated_at=_to_dt(row["updated_at"]) if row.get("updated_at") else None,
        )


def _entity_key(name: str) -> str:
    return hashlib.md5(name.encode()).hexdigest()[:16]


def _to_dt(value) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))
