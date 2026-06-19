import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from .base import BaseMemoryStore
from ..models import EpisodicMemory, Outcome


class EpisodicMemoryStore(BaseMemoryStore):
    """
    Stores specific experiences tied to time and context.

    PostgreSQL — structured metadata and filtering by session/agent/outcome.
    Weaviate   — semantic similarity search over episode content.
    ArangoDB   — episode graph; episodes can be linked to each other and to
                 reflective memories via the episode_reflection edge collection.
    """

    # ------------------------------------------------------------------
    # Core CRUD
    # ------------------------------------------------------------------

    def store(self, memory: EpisodicMemory) -> str:
        embedding = self._embed(memory.content)
        memory.embedding = embedding

        self.postgres.execute(
            """
            INSERT INTO episodic_memories
                (id, session_id, agent_id, content, context, outcome, importance, metadata, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                memory.id, memory.session_id, memory.agent_id, memory.content,
                json.dumps(memory.context), memory.outcome.value,
                memory.importance, json.dumps(memory.metadata), memory.created_at,
            ),
        )

        self.weaviate.insert("episodic", memory.id, embedding)

        self.arango.insert_node("episodic", {
            "_key": memory.id,
            "session_id": memory.session_id,
            "agent_id": memory.agent_id,
            "content": memory.content,
            "outcome": memory.outcome.value,
            "importance": memory.importance,
            "created_at": memory.created_at.isoformat(),
        })

        return memory.id

    def retrieve(self, memory_id: str) -> Optional[EpisodicMemory]:
        row = self.postgres.execute_one(
            "SELECT * FROM episodic_memories WHERE id = %s", (memory_id,)
        )
        return self._from_row(row) if row else None

    def search(self, query: str, top_k: int = 5) -> List[EpisodicMemory]:
        hits = self.weaviate.search("episodic", self._embed(query), top_k)
        results = []
        for memory_id, score in hits:
            mem = self.retrieve(memory_id)
            if mem:
                mem.score = score
                results.append(mem)
        return results

    def update(self, memory: EpisodicMemory) -> None:
        embedding = self._embed(memory.content)
        memory.embedding = embedding

        self.postgres.execute(
            """
            UPDATE episodic_memories
            SET content=%s, context=%s, outcome=%s, importance=%s, metadata=%s
            WHERE id=%s
            """,
            (
                memory.content, json.dumps(memory.context), memory.outcome.value,
                memory.importance, json.dumps(memory.metadata), memory.id,
            ),
        )
        self.weaviate.update("episodic", memory.id, embedding)
        self.arango.update_node("episodic", memory.id, {
            "content": memory.content,
            "outcome": memory.outcome.value,
            "importance": memory.importance,
        })

    def delete(self, memory_id: str) -> None:
        self.postgres.execute("DELETE FROM episodic_memories WHERE id = %s", (memory_id,))
        self.weaviate.delete("episodic", memory_id)
        self.arango.delete_node("episodic", memory_id)

    # ------------------------------------------------------------------
    # Filtering helpers
    # ------------------------------------------------------------------

    def get_by_session(self, session_id: str) -> List[EpisodicMemory]:
        rows = self.postgres.execute(
            "SELECT * FROM episodic_memories WHERE session_id = %s ORDER BY created_at",
            (session_id,),
        )
        return [self._from_row(r) for r in rows]

    def get_by_agent(self, agent_id: str, limit: int = 50) -> List[EpisodicMemory]:
        rows = self.postgres.execute(
            "SELECT * FROM episodic_memories WHERE agent_id = %s ORDER BY created_at DESC LIMIT %s",
            (agent_id, limit),
        )
        return [self._from_row(r) for r in rows]

    def get_by_outcome(self, outcome: Outcome) -> List[EpisodicMemory]:
        rows = self.postgres.execute(
            "SELECT * FROM episodic_memories WHERE outcome = %s ORDER BY created_at DESC",
            (outcome.value,),
        )
        return [self._from_row(r) for r in rows]

    def get_high_importance(self, threshold: float = 0.7) -> List[EpisodicMemory]:
        rows = self.postgres.execute(
            "SELECT * FROM episodic_memories WHERE importance >= %s ORDER BY importance DESC",
            (threshold,),
        )
        return [self._from_row(r) for r in rows]

    # ------------------------------------------------------------------
    # Graph operations
    # ------------------------------------------------------------------

    def link_episodes(self, from_id: str, to_id: str, relation: str = "related"):
        """Create a directed edge between two episode nodes."""
        self.arango.insert_edge(
            "memory_relations", "episodic", from_id, "episodic", to_id,
            {"relation": relation},
        )

    def get_related_episodes(self, memory_id: str) -> List[Dict[str, Any]]:
        return self.arango.get_related("episodic", memory_id, "memory_relations")

    # ------------------------------------------------------------------
    # Deserialisation
    # ------------------------------------------------------------------

    def _from_row(self, row: Dict[str, Any]) -> EpisodicMemory:
        return EpisodicMemory(
            id=row["id"],
            content=row["content"],
            session_id=row.get("session_id") or "",
            agent_id=row.get("agent_id") or "",
            context=row.get("context") or {},
            outcome=Outcome(row.get("outcome", "unknown")),
            importance=float(row.get("importance", 0.5)),
            metadata=row.get("metadata") or {},
            created_at=_to_dt(row.get("created_at")),
        )


def _to_dt(value) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))
