import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from .base import BaseMemoryStore
from ..models import ReflectiveMemory


class ReflectiveMemoryStore(BaseMemoryStore):
    """
    Stores self-generated lessons extracted from past experiences.

    PostgreSQL — structured lesson and suggestion text, application counter.
    Weaviate   — similarity search over reflection content + lesson.
    ArangoDB   — episode_reflection edges link episode nodes to the reflections
                 they generated, preserving provenance.
    """

    # ------------------------------------------------------------------
    # Core CRUD
    # ------------------------------------------------------------------

    def store(self, memory: ReflectiveMemory) -> str:
        embedding = self._embed(
            f"{memory.content} {memory.lesson} {memory.improvement_suggestion}"
        )
        memory.embedding = embedding

        self.postgres.execute(
            """
            INSERT INTO reflective_memories
                (id, source_episode_id, content, lesson, improvement_suggestion,
                 confidence, applied_count, metadata, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                memory.id, memory.source_episode_id, memory.content,
                memory.lesson, memory.improvement_suggestion, memory.confidence,
                memory.applied_count, json.dumps(memory.metadata), memory.created_at,
            ),
        )

        self.weaviate.insert("reflective", memory.id, embedding)

        self.arango.insert_node("reflective", {
            "_key": memory.id,
            "content": memory.content,
            "lesson": memory.lesson,
            "improvement_suggestion": memory.improvement_suggestion,
            "confidence": memory.confidence,
            "source_episode_id": memory.source_episode_id,
        })

        if memory.source_episode_id:
            try:
                self.arango.insert_edge(
                    "episode_reflection",
                    "episodic", memory.source_episode_id,
                    "reflective", memory.id,
                    {"relation": "generated_reflection"},
                )
            except Exception:
                pass  # source episode node may not exist in ArangoDB

        return memory.id

    def retrieve(self, memory_id: str) -> Optional[ReflectiveMemory]:
        row = self.postgres.execute_one(
            "SELECT * FROM reflective_memories WHERE id = %s", (memory_id,)
        )
        return self._from_row(row) if row else None

    def search(self, query: str, top_k: int = 5) -> List[ReflectiveMemory]:
        hits = self.weaviate.search("reflective", self._embed(query), top_k)
        results = []
        for memory_id, score in hits:
            mem = self.retrieve(memory_id)
            if mem:
                mem.score = score
                results.append(mem)
        return results

    def update(self, memory: ReflectiveMemory) -> None:
        embedding = self._embed(
            f"{memory.content} {memory.lesson} {memory.improvement_suggestion}"
        )
        memory.embedding = embedding

        self.postgres.execute(
            """
            UPDATE reflective_memories
            SET content=%s, lesson=%s, improvement_suggestion=%s,
                confidence=%s, applied_count=%s, metadata=%s
            WHERE id=%s
            """,
            (
                memory.content, memory.lesson, memory.improvement_suggestion,
                memory.confidence, memory.applied_count,
                json.dumps(memory.metadata), memory.id,
            ),
        )
        self.weaviate.update("reflective", memory.id, embedding)
        self.arango.update_node("reflective", memory.id, {
            "content": memory.content,
            "lesson": memory.lesson,
            "confidence": memory.confidence,
        })

    def delete(self, memory_id: str) -> None:
        self.postgres.execute("DELETE FROM reflective_memories WHERE id = %s", (memory_id,))
        self.weaviate.delete("reflective", memory_id)
        self.arango.delete_node("reflective", memory_id)

    # ------------------------------------------------------------------
    # Application tracking
    # ------------------------------------------------------------------

    def mark_applied(self, memory_id: str) -> None:
        """Increment the counter each time this reflection influences a decision."""
        self.postgres.execute(
            "UPDATE reflective_memories SET applied_count = applied_count + 1 WHERE id = %s",
            (memory_id,),
        )
        row = self.postgres.execute_one(
            "SELECT applied_count FROM reflective_memories WHERE id = %s", (memory_id,)
        )
        if row:
            self.arango.update_node("reflective", memory_id, {"applied_count": row["applied_count"]})

    # ------------------------------------------------------------------
    # Filtering helpers
    # ------------------------------------------------------------------

    def get_from_episode(self, episode_id: str) -> List[ReflectiveMemory]:
        rows = self.postgres.execute(
            "SELECT * FROM reflective_memories WHERE source_episode_id = %s",
            (episode_id,),
        )
        return [self._from_row(r) for r in rows]

    def get_most_applied(self, limit: int = 10) -> List[ReflectiveMemory]:
        rows = self.postgres.execute(
            "SELECT * FROM reflective_memories ORDER BY applied_count DESC LIMIT %s",
            (limit,),
        )
        return [self._from_row(r) for r in rows]

    def get_above_confidence(self, threshold: float = 0.8) -> List[ReflectiveMemory]:
        rows = self.postgres.execute(
            "SELECT * FROM reflective_memories WHERE confidence >= %s ORDER BY confidence DESC",
            (threshold,),
        )
        return [self._from_row(r) for r in rows]

    # ------------------------------------------------------------------
    # Graph traversal
    # ------------------------------------------------------------------

    def get_reflections_for_episode(self, episode_id: str) -> List[Dict[str, Any]]:
        """Return all reflection nodes linked from an episodic node."""
        return self.arango.get_related("episodic", episode_id, "episode_reflection")

    # ------------------------------------------------------------------
    # Deserialisation
    # ------------------------------------------------------------------

    def _from_row(self, row: Dict[str, Any]) -> ReflectiveMemory:
        return ReflectiveMemory(
            id=row["id"],
            content=row["content"],
            source_episode_id=row.get("source_episode_id"),
            lesson=row.get("lesson") or "",
            improvement_suggestion=row.get("improvement_suggestion") or "",
            confidence=float(row.get("confidence", 1.0)),
            applied_count=int(row.get("applied_count", 0)),
            metadata=row.get("metadata") or {},
            created_at=_to_dt(row.get("created_at")),
        )


def _to_dt(value) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))
