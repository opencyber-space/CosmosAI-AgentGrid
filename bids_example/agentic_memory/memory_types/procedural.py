import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from .base import BaseMemoryStore
from ..models import ProceduralMemory, ProcedureStep


class ProceduralMemoryStore(BaseMemoryStore):
    """
    Stores named skills as ordered step sequences with trigger conditions.

    PostgreSQL — procedures + procedure_steps (relational steps with FK cascade).
    Weaviate   — semantic search over procedure name + description + step text.
    ArangoDB   — procedure nodes; can be linked to episodes that triggered them.
    """

    # ------------------------------------------------------------------
    # Core CRUD
    # ------------------------------------------------------------------

    def store(self, memory: ProceduralMemory) -> str:
        embedding = self._procedure_embedding(memory)
        memory.embedding = embedding
        if not memory.updated_at:
            memory.updated_at = memory.created_at

        self.postgres.execute(
            """
            INSERT INTO procedures
                (id, name, description, trigger_conditions, success_rate, use_count, metadata, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                memory.id, memory.name, memory.content,
                json.dumps(memory.trigger_conditions),
                memory.success_rate, memory.use_count,
                json.dumps(memory.metadata), memory.created_at, memory.updated_at,
            ),
        )
        self._insert_steps(memory.id, memory.steps)

        self.weaviate.insert("procedural", memory.id, embedding)

        self.arango.insert_node("procedural", {
            "_key": memory.id,
            "name": memory.name,
            "description": memory.content,
            "trigger_conditions": memory.trigger_conditions,
            "step_count": len(memory.steps),
            "success_rate": memory.success_rate,
            "use_count": memory.use_count,
        })

        return memory.id

    def retrieve(self, memory_id: str) -> Optional[ProceduralMemory]:
        row = self.postgres.execute_one("SELECT * FROM procedures WHERE id = %s", (memory_id,))
        if not row:
            return None
        steps = self._fetch_steps(memory_id)
        return self._from_row(row, steps)

    def search(self, query: str, top_k: int = 5) -> List[ProceduralMemory]:
        hits = self.weaviate.search("procedural", self._embed(query), top_k)
        results = []
        for memory_id, score in hits:
            mem = self.retrieve(memory_id)
            if mem:
                mem.score = score
                results.append(mem)
        return results

    def update(self, memory: ProceduralMemory) -> None:
        embedding = self._procedure_embedding(memory)
        memory.embedding = embedding
        memory.updated_at = datetime.utcnow()

        self.postgres.execute(
            """
            UPDATE procedures
            SET name=%s, description=%s, trigger_conditions=%s,
                success_rate=%s, use_count=%s, metadata=%s, updated_at=%s
            WHERE id=%s
            """,
            (
                memory.name, memory.content, json.dumps(memory.trigger_conditions),
                memory.success_rate, memory.use_count,
                json.dumps(memory.metadata), memory.updated_at, memory.id,
            ),
        )
        self.postgres.execute("DELETE FROM procedure_steps WHERE procedure_id = %s", (memory.id,))
        self._insert_steps(memory.id, memory.steps)

        self.weaviate.update("procedural", memory.id, embedding)
        self.arango.update_node("procedural", memory.id, {
            "name": memory.name,
            "step_count": len(memory.steps),
            "success_rate": memory.success_rate,
            "use_count": memory.use_count,
        })

    def delete(self, memory_id: str) -> None:
        self.postgres.execute("DELETE FROM procedures WHERE id = %s", (memory_id,))
        self.weaviate.delete("procedural", memory_id)
        self.arango.delete_node("procedural", memory_id)

    # ------------------------------------------------------------------
    # Execution tracking
    # ------------------------------------------------------------------

    def record_execution(self, memory_id: str, success: bool) -> None:
        """Update rolling success rate and increment use count."""
        row = self.postgres.execute_one(
            "SELECT success_rate, use_count FROM procedures WHERE id = %s", (memory_id,)
        )
        if not row:
            return
        old_rate = float(row["success_rate"])
        old_count = int(row["use_count"])
        new_count = old_count + 1
        new_rate = (old_rate * old_count + (1.0 if success else 0.0)) / new_count

        self.postgres.execute(
            "UPDATE procedures SET success_rate=%s, use_count=%s, updated_at=NOW() WHERE id=%s",
            (new_rate, new_count, memory_id),
        )
        self.arango.update_node("procedural", memory_id, {
            "success_rate": new_rate,
            "use_count": new_count,
        })

    # ------------------------------------------------------------------
    # Filtering helpers
    # ------------------------------------------------------------------

    def get_by_name(self, name: str) -> Optional[ProceduralMemory]:
        row = self.postgres.execute_one("SELECT * FROM procedures WHERE name = %s", (name,))
        if not row:
            return None
        return self._from_row(row, self._fetch_steps(row["id"]))

    def get_top_procedures(self, limit: int = 10) -> List[ProceduralMemory]:
        rows = self.postgres.execute(
            "SELECT * FROM procedures ORDER BY success_rate DESC, use_count DESC LIMIT %s",
            (limit,),
        )
        return [self._from_row(r, self._fetch_steps(r["id"])) for r in rows]

    def search_by_trigger(self, condition: str) -> List[ProceduralMemory]:
        """Semantic search for procedures whose trigger conditions match a description."""
        return self.search(condition)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _procedure_embedding(self, memory: ProceduralMemory) -> List[float]:
        steps_text = " ".join(
            f"{s.action} {s.expected_outcome}" for s in memory.steps
        )
        return self._embed(f"{memory.name} {memory.content} {steps_text}")

    def _insert_steps(self, procedure_id: str, steps: List[ProcedureStep]):
        for step in steps:
            self.postgres.execute(
                """
                INSERT INTO procedure_steps (id, procedure_id, step_order, action, parameters, expected_outcome)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    str(uuid.uuid4()), procedure_id, step.step_order,
                    step.action, json.dumps(step.parameters), step.expected_outcome,
                ),
            )

    def _fetch_steps(self, procedure_id: str) -> List[ProcedureStep]:
        rows = self.postgres.execute(
            "SELECT * FROM procedure_steps WHERE procedure_id = %s ORDER BY step_order",
            (procedure_id,),
        )
        return [
            ProcedureStep(
                step_order=r["step_order"],
                action=r["action"],
                parameters=r.get("parameters") or {},
                expected_outcome=r.get("expected_outcome") or "",
            )
            for r in rows
        ]

    def _from_row(self, row: Dict[str, Any], steps: List[ProcedureStep] = None) -> ProceduralMemory:
        return ProceduralMemory(
            id=row["id"],
            content=row.get("description") or "",
            name=row.get("name") or "",
            trigger_conditions=row.get("trigger_conditions") or [],
            steps=steps or [],
            success_rate=float(row.get("success_rate", 0.0)),
            use_count=int(row.get("use_count", 0)),
            metadata=row.get("metadata") or {},
            created_at=_to_dt(row.get("created_at")),
            updated_at=_to_dt(row["updated_at"]) if row.get("updated_at") else None,
        )


def _to_dt(value) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))
