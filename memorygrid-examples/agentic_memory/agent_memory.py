from typing import Any, Dict, List, Optional, Tuple

from .backends.arango_client import ArangoBackend
from .backends.weaviate_client import WeaviateClient
from .backends.postgres_client import PostgresClient
from .config import MemoryConfig
from .embeddings import EmbeddingProvider
from .memory_types.episodic import EpisodicMemoryStore
from .memory_types.procedural import ProceduralMemoryStore
from .memory_types.reflective import ReflectiveMemoryStore
from .memory_types.reward import RewardMemoryStore
from .memory_types.semantic import SemanticMemoryStore
from .models import (
    EpisodicMemory,
    Outcome,
    ProceduralMemory,
    ProcedureStep,
    ReflectiveMemory,
    RewardMemory,
    SemanticMemory,
)


class AgentMemory:
    """
    Unified façade over all five agentic memory types.

    Usage::

        mem = AgentMemory(config)

        # Store
        ep = mem.remember_episode("User asked about the weather", session_id="s1")
        fact = mem.know_fact("Paris", "is_capital_of", "France")
        proc = mem.learn_procedure("send_email", steps=[...])
        ref = mem.reflect("I should ask for clarification", lesson="...")
        rw = mem.record_reward("state: low battery", "recharge", reward=1.0)

        # Search across all types at once
        results = mem.recall("weather questions")

        # Access individual stores for richer APIs
        mem.episodic.get_by_session("s1")
        mem.semantic.get_neighbors("Paris")
        mem.procedural.record_execution(proc.id, success=True)
        mem.reflective.mark_applied(ref.id)
        mem.reward.get_best_action("state: low battery")
    """

    def __init__(
        self,
        config: Optional[MemoryConfig] = None,
        embedder: Optional[EmbeddingProvider] = None,
        openai_api_key: Optional[str] = None,
    ):
        self.config = config or MemoryConfig()
        self._embedder = embedder or EmbeddingProvider(
            model=self.config.embedding_model,
            dim=self.config.weaviate.embedding_dim,
            api_key=openai_api_key,
        )
        self._weaviate = WeaviateClient(self.config.weaviate)
        self._arango = ArangoBackend(self.config.arango)
        self._postgres = PostgresClient(self.config.postgres)

        _kw = dict(
            weaviate=self._weaviate,
            arango=self._arango,
            postgres=self._postgres,
            embedder=self._embedder,
            config=self.config,
        )
        self.episodic: EpisodicMemoryStore = EpisodicMemoryStore(**_kw)
        self.semantic: SemanticMemoryStore = SemanticMemoryStore(**_kw)
        self.procedural: ProceduralMemoryStore = ProceduralMemoryStore(**_kw)
        self.reflective: ReflectiveMemoryStore = ReflectiveMemoryStore(**_kw)
        self.reward: RewardMemoryStore = RewardMemoryStore(**_kw)

    # ------------------------------------------------------------------
    # Convenience write helpers
    # ------------------------------------------------------------------

    def remember_episode(
        self,
        content: str,
        *,
        session_id: str = "",
        agent_id: str = "",
        context: Optional[Dict[str, Any]] = None,
        outcome: Outcome = Outcome.UNKNOWN,
        importance: float = 0.5,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> EpisodicMemory:
        memory = EpisodicMemory(
            content=content,
            session_id=session_id,
            agent_id=agent_id,
            context=context or {},
            outcome=outcome,
            importance=importance,
            metadata=metadata or {},
        )
        self.episodic.store(memory)
        return memory

    def know_fact(
        self,
        subject: str,
        predicate: str,
        object_: str,
        *,
        content: str = "",
        confidence: float = 1.0,
        source: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SemanticMemory:
        memory = SemanticMemory(
            content=content or f"{subject} {predicate} {object_}",
            subject=subject,
            predicate=predicate,
            object=object_,
            confidence=confidence,
            source=source,
            metadata=metadata or {},
        )
        self.semantic.store(memory)
        return memory

    def learn_procedure(
        self,
        name: str,
        steps: List[Dict[str, Any]],
        *,
        description: str = "",
        trigger_conditions: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ProceduralMemory:
        procedure_steps = [
            ProcedureStep(
                step_order=i,
                action=s.get("action", ""),
                parameters=s.get("parameters", {}),
                expected_outcome=s.get("expected_outcome", ""),
            )
            for i, s in enumerate(steps)
        ]
        memory = ProceduralMemory(
            content=description,
            name=name,
            steps=procedure_steps,
            trigger_conditions=trigger_conditions or [],
            metadata=metadata or {},
        )
        self.procedural.store(memory)
        return memory

    def reflect(
        self,
        content: str,
        lesson: str,
        *,
        improvement_suggestion: str = "",
        source_episode_id: Optional[str] = None,
        confidence: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ReflectiveMemory:
        memory = ReflectiveMemory(
            content=content,
            lesson=lesson,
            improvement_suggestion=improvement_suggestion,
            source_episode_id=source_episode_id,
            confidence=confidence,
            metadata=metadata or {},
        )
        self.reflective.store(memory)
        return memory

    def record_reward(
        self,
        state_description: str,
        action: str,
        reward: float,
        *,
        outcome: str = "",
        policy: str = "default",
        context: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> RewardMemory:
        memory = RewardMemory(
            content=state_description,
            state_description=state_description,
            action=action,
            reward=reward,
            outcome=outcome,
            policy=policy,
            context=context or {},
            metadata=metadata or {},
        )
        self.reward.store(memory)
        return memory

    # ------------------------------------------------------------------
    # Cross-type retrieval
    # ------------------------------------------------------------------

    def recall(self, query: str, top_k: int = 5) -> Dict[str, List]:
        """Search all five memory types simultaneously. Returns a dict keyed by type."""
        return {
            "episodic": self.episodic.search(query, top_k),
            "semantic": self.semantic.search(query, top_k),
            "procedural": self.procedural.search(query, top_k),
            "reflective": self.reflective.search(query, top_k),
            "reward": self.reward.search(query, top_k),
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self):
        self._postgres.close()
        self._weaviate.disconnect()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
