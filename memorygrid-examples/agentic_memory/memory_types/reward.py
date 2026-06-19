import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseMemoryStore
from ..models import RewardMemory


class RewardMemoryStore(BaseMemoryStore):
    """
    Stores (state, action, reward) tuples for reinforcement-style learning.

    PostgreSQL — structured storage with policy/action indices; aggregate queries.
    Weaviate   — nearest-neighbour lookup over state embeddings for action suggestion.
    ArangoDB   — state-transition graph: edges represent actions taken between states.
    """

    # ------------------------------------------------------------------
    # Core CRUD
    # ------------------------------------------------------------------

    def store(self, memory: RewardMemory) -> str:
        embedding = self._embed(
            f"{memory.state_description} {memory.action} {memory.outcome}"
        )
        memory.embedding = embedding

        self.postgres.execute(
            """
            INSERT INTO reward_memories
                (id, state_description, action, reward, outcome, policy, context, metadata, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                memory.id, memory.state_description, memory.action,
                memory.reward, memory.outcome, memory.policy,
                json.dumps(memory.context), json.dumps(memory.metadata), memory.created_at,
            ),
        )

        self.weaviate.insert("reward", memory.id, embedding)

        self.arango.insert_node("reward", {
            "_key": memory.id,
            "state_description": memory.state_description,
            "action": memory.action,
            "reward": memory.reward,
            "outcome": memory.outcome,
            "policy": memory.policy,
        })

        return memory.id

    def retrieve(self, memory_id: str) -> Optional[RewardMemory]:
        row = self.postgres.execute_one(
            "SELECT * FROM reward_memories WHERE id = %s", (memory_id,)
        )
        return self._from_row(row) if row else None

    def search(self, query: str, top_k: int = 5) -> List[RewardMemory]:
        hits = self.weaviate.search("reward", self._embed(query), top_k)
        results = []
        for memory_id, score in hits:
            mem = self.retrieve(memory_id)
            if mem:
                mem.score = score
                results.append(mem)
        return results

    def update(self, memory: RewardMemory) -> None:
        embedding = self._embed(
            f"{memory.state_description} {memory.action} {memory.outcome}"
        )
        memory.embedding = embedding

        self.postgres.execute(
            """
            UPDATE reward_memories
            SET state_description=%s, action=%s, reward=%s, outcome=%s,
                policy=%s, context=%s, metadata=%s
            WHERE id=%s
            """,
            (
                memory.state_description, memory.action, memory.reward,
                memory.outcome, memory.policy,
                json.dumps(memory.context), json.dumps(memory.metadata), memory.id,
            ),
        )
        self.weaviate.update("reward", memory.id, embedding)
        self.arango.update_node("reward", memory.id, {
            "state_description": memory.state_description,
            "action": memory.action,
            "reward": memory.reward,
        })

    def delete(self, memory_id: str) -> None:
        self.postgres.execute("DELETE FROM reward_memories WHERE id = %s", (memory_id,))
        self.weaviate.delete("reward", memory_id)
        self.arango.delete_node("reward", memory_id)

    # ------------------------------------------------------------------
    # Decision support
    # ------------------------------------------------------------------

    def get_best_action(
        self, state_description: str, policy: str = "default", top_k: int = 20
    ) -> Optional[Tuple[str, float]]:
        """
        Find the action with the highest average reward for states similar to
        the given description. Returns (action, avg_reward) or None.
        """
        candidates = self.search(state_description, top_k)
        policy_matches = [m for m in candidates if m.policy == policy] or candidates

        if not policy_matches:
            return None

        action_rewards: Dict[str, List[float]] = {}
        for mem in policy_matches:
            action_rewards.setdefault(mem.action, []).append(mem.reward)

        best = max(action_rewards, key=lambda a: sum(action_rewards[a]) / len(action_rewards[a]))
        avg = sum(action_rewards[best]) / len(action_rewards[best])
        return best, avg

    def get_action_stats(self, policy: str = "default") -> Dict[str, Dict[str, float]]:
        """Per-action reward statistics for a given policy."""
        rows = self.postgres.execute(
            """
            SELECT action,
                   COUNT(*)        AS count,
                   AVG(reward)     AS avg_reward,
                   MAX(reward)     AS max_reward,
                   MIN(reward)     AS min_reward
            FROM reward_memories
            WHERE policy = %s
            GROUP BY action
            ORDER BY avg_reward DESC
            """,
            (policy,),
        )
        return {
            r["action"]: {
                "count": int(r["count"]),
                "avg_reward": float(r["avg_reward"]),
                "max_reward": float(r["max_reward"]),
                "min_reward": float(r["min_reward"]),
            }
            for r in rows
        }

    def get_policy_summary(self, policy: str = "default") -> Dict[str, Any]:
        row = self.postgres.execute_one(
            """
            SELECT COUNT(*)             AS total,
                   AVG(reward)          AS avg_reward,
                   MAX(reward)          AS max_reward,
                   MIN(reward)          AS min_reward,
                   COUNT(DISTINCT action) AS unique_actions
            FROM reward_memories
            WHERE policy = %s
            """,
            (policy,),
        )
        return dict(row) if row else {}

    # ------------------------------------------------------------------
    # Filtering helpers
    # ------------------------------------------------------------------

    def get_by_policy(self, policy: str, limit: int = 100) -> List[RewardMemory]:
        rows = self.postgres.execute(
            "SELECT * FROM reward_memories WHERE policy = %s ORDER BY reward DESC LIMIT %s",
            (policy, limit),
        )
        return [self._from_row(r) for r in rows]

    def get_top_rewards(self, limit: int = 10, policy: str = "default") -> List[RewardMemory]:
        rows = self.postgres.execute(
            "SELECT * FROM reward_memories WHERE policy = %s ORDER BY reward DESC LIMIT %s",
            (policy, limit),
        )
        return [self._from_row(r) for r in rows]

    # ------------------------------------------------------------------
    # State-transition graph
    # ------------------------------------------------------------------

    def record_transition(self, from_id: str, to_id: str, action: str):
        """Record that taking `action` in state `from_id` led to state `to_id`."""
        self.arango.insert_edge(
            "memory_relations", "reward", from_id, "reward", to_id,
            {"relation": "state_transition", "action": action},
        )

    def get_successor_states(self, memory_id: str) -> List[Dict[str, Any]]:
        return self.arango.get_related("reward", memory_id, "memory_relations")

    # ------------------------------------------------------------------
    # Deserialisation
    # ------------------------------------------------------------------

    def _from_row(self, row: Dict[str, Any]) -> RewardMemory:
        return RewardMemory(
            id=row["id"],
            content=row.get("state_description") or "",
            state_description=row.get("state_description") or "",
            action=row.get("action") or "",
            reward=float(row.get("reward", 0.0)),
            outcome=row.get("outcome") or "",
            policy=row.get("policy") or "default",
            context=row.get("context") or {},
            metadata=row.get("metadata") or {},
            created_at=_to_dt(row.get("created_at")),
        )


def _to_dt(value) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))
