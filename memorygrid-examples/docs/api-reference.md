# API Reference

---

## `AgentMemory`

**File:** [`agentic_memory/agent_memory.py`](../agentic_memory/agent_memory.py)

The single entry point. Initialises all three backends and all five stores.

```python
from agentic_memory import AgentMemory
from agentic_memory.config import MemoryConfig

mem = AgentMemory()                   # uses all defaults (localhost)
mem = AgentMemory(config)             # custom MemoryConfig
with AgentMemory(config) as mem: ... # context manager — calls close() on exit
```

### Constructor

```python
AgentMemory(config: Optional[MemoryConfig] = None)
```

On init: connects to all three backends, creates missing database/collections/tables,
loads the embedding model lazily.

### Store references

```python
mem.episodic    # EpisodicMemoryStore
mem.semantic    # SemanticMemoryStore
mem.procedural  # ProceduralMemoryStore
mem.reflective  # ReflectiveMemoryStore
mem.reward      # RewardMemoryStore
```

### Write helpers

#### `remember_episode`

```python
mem.remember_episode(
    content: str,
    *,
    session_id: str = "",
    agent_id: str = "",
    context: Optional[Dict[str, Any]] = None,
    outcome: Outcome = Outcome.UNKNOWN,
    importance: float = 0.5,
    metadata: Optional[Dict[str, Any]] = None,
) -> EpisodicMemory
```

Store a time-bound event. Returns the created `EpisodicMemory` with its assigned `id`.

#### `know_fact`

```python
mem.know_fact(
    subject: str,
    predicate: str,
    object_: str,
    *,
    content: str = "",           # defaults to "subject predicate object"
    confidence: float = 1.0,
    source: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> SemanticMemory
```

Store a subject–predicate–object knowledge triple. Also auto-creates entity nodes and
a knowledge graph edge in ArangoDB.

#### `learn_procedure`

```python
mem.learn_procedure(
    name: str,
    steps: List[Dict[str, Any]],  # each: {"action", "parameters", "expected_outcome"}
    *,
    description: str = "",
    trigger_conditions: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> ProceduralMemory
```

Store a named skill. `steps` is a list of dicts; `step_order` is assigned by list position.

#### `reflect`

```python
mem.reflect(
    content: str,
    lesson: str,
    *,
    improvement_suggestion: str = "",
    source_episode_id: Optional[str] = None,
    confidence: float = 1.0,
    metadata: Optional[Dict[str, Any]] = None,
) -> ReflectiveMemory
```

Store a self-generated insight. If `source_episode_id` is provided, an
`episode_reflection` edge is created in ArangoDB preserving provenance.

#### `record_reward`

```python
mem.record_reward(
    state_description: str,
    action: str,
    reward: float,
    *,
    outcome: str = "",
    policy: str = "default",
    context: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> RewardMemory
```

Store a (state, action, reward) tuple.

### Cross-type retrieval

#### `recall`

```python
mem.recall(query: str, top_k: int = 5) -> Dict[str, List]
```

Semantic search across all five memory types simultaneously. Returns:

```python
{
    "episodic":   List[EpisodicMemory],
    "semantic":   List[SemanticMemory],
    "procedural": List[ProceduralMemory],
    "reflective": List[ReflectiveMemory],
    "reward":     List[RewardMemory],
}
```

Each returned object has a `.score` attribute (cosine similarity, 0–1).

### Lifecycle

```python
mem.close()          # disconnect Postgres and Weaviate
mem.__enter__()      # returns self
mem.__exit__(...)    # calls close()
```

---

## `BaseMemoryStore`

**File:** [`agentic_memory/memory_types/base.py`](../agentic_memory/memory_types/base.py)

Abstract base class implemented by all five stores.

```python
store(memory: BaseMemory) -> str
```
Persist to all three backends. Returns the memory `id`.

```python
retrieve(memory_id: str) -> Optional[BaseMemory]
```
Fetch by exact ID from Postgres. Returns `None` if not found.

```python
search(query: str, top_k: int = 5) -> List[BaseMemory]
```
Embed `query`, search Weaviate for top_k, hydrate from Postgres. Results include `.score`.

```python
update(memory: BaseMemory) -> None
```
Overwrite in all three backends. Re-embeds the content.

```python
delete(memory_id: str) -> None
```
Remove from all three backends.

---

## `EpisodicMemoryStore`

**File:** [`agentic_memory/memory_types/episodic.py`](../agentic_memory/memory_types/episodic.py)

Inherits all `BaseMemoryStore` methods. Additional API:

### Filtering

```python
get_by_session(session_id: str) -> List[EpisodicMemory]
```
All episodes for a session, ordered by `created_at` ascending.

```python
get_by_agent(agent_id: str, limit: int = 50) -> List[EpisodicMemory]
```
Most recent episodes for an agent (newest first).

```python
get_by_outcome(outcome: Outcome) -> List[EpisodicMemory]
```
All episodes with a given outcome, newest first.

```python
get_high_importance(threshold: float = 0.7) -> List[EpisodicMemory]
```
All episodes with `importance >= threshold`, highest first.

### Graph

```python
link_episodes(from_id: str, to_id: str, relation: str = "related") -> None
```
Create a directed `memory_relations` edge between two episode nodes in ArangoDB.

```python
get_related_episodes(memory_id: str) -> List[Dict[str, Any]]
```
ArangoDB OUTBOUND traversal: all episode nodes directly connected to this one.

---

## `SemanticMemoryStore`

**File:** [`agentic_memory/memory_types/semantic.py`](../agentic_memory/memory_types/semantic.py)

### Triple lookups

```python
get_by_subject(subject: str) -> List[SemanticMemory]
```
All facts about a subject, ordered by `confidence DESC`.

```python
get_by_predicate(predicate: str) -> List[SemanticMemory]
```
All facts using a predicate, ordered by `confidence DESC`.

```python
get_triple(subject: str, predicate: str) -> Optional[SemanticMemory]
```
Single best-confidence fact for a (subject, predicate) pair.

```python
get_above_confidence(threshold: float = 0.8) -> List[SemanticMemory]
```
All facts with `confidence >= threshold`.

### Knowledge graph traversal

```python
get_neighbors(entity: str, direction: str = "OUTBOUND") -> List[Dict[str, Any]]
```
All entity nodes directly connected to this entity. `direction` can be
`"OUTBOUND"`, `"INBOUND"`, or `"ANY"`.

```python
find_path(from_entity: str, to_entity: str) -> List[Dict[str, Any]]
```
Shortest path between two entities in the ArangoDB knowledge graph.

---

## `ProceduralMemoryStore`

**File:** [`agentic_memory/memory_types/procedural.py`](../agentic_memory/memory_types/procedural.py)

### Execution tracking

```python
record_execution(memory_id: str, success: bool) -> None
```
Update rolling `success_rate` and increment `use_count`.
Formula: `new_rate = (old_rate × old_count + (1.0 if success else 0.0)) / new_count`

### Filtering

```python
get_by_name(name: str) -> Optional[ProceduralMemory]
```
Fetch by exact procedure name.

```python
get_top_procedures(limit: int = 10) -> List[ProceduralMemory]
```
Most reliable procedures: `ORDER BY success_rate DESC, use_count DESC`.

```python
search_by_trigger(condition: str) -> List[ProceduralMemory]
```
Semantic search over procedures using a trigger condition description.
Delegates to `search()` — the embedding includes trigger condition text.

---

## `ReflectiveMemoryStore`

**File:** [`agentic_memory/memory_types/reflective.py`](../agentic_memory/memory_types/reflective.py)

### Application tracking

```python
mark_applied(memory_id: str) -> None
```
Atomically increment `applied_count` in Postgres (`applied_count = applied_count + 1`),
then sync the new value to ArangoDB.

### Filtering

```python
get_from_episode(episode_id: str) -> List[ReflectiveMemory]
```
All reflections that cite a given episode as their source.

```python
get_most_applied(limit: int = 10) -> List[ReflectiveMemory]
```
Reflections that have most influenced decisions: `ORDER BY applied_count DESC`.

```python
get_above_confidence(threshold: float = 0.8) -> List[ReflectiveMemory]
```
High-certainty reflections only.

### Graph traversal

```python
get_reflections_for_episode(episode_id: str) -> List[Dict[str, Any]]
```
ArangoDB OUTBOUND traversal over `episode_reflection` edges — all reflection
nodes linked from an episode node.

---

## `RewardMemoryStore`

**File:** [`agentic_memory/memory_types/reward.py`](../agentic_memory/memory_types/reward.py)

### Decision support

```python
get_best_action(
    state_description: str,
    policy: str = "default",
    top_k: int = 20,
) -> Optional[Tuple[str, float]]
```
Find the best action for a state similar to `state_description`.

1. Vector search for up to `top_k` similar past states
2. Filter to `policy` (falls back to all candidates if none match)
3. Group by `action`, compute `avg(reward)` per action
4. Return `(action, avg_reward)` for the highest-scoring action, or `None`

```python
get_action_stats(policy: str = "default") -> Dict[str, Dict[str, float]]
```
Postgres `GROUP BY action` aggregate. Returns:
```python
{
    "action_name": {
        "count": int,
        "avg_reward": float,
        "max_reward": float,
        "min_reward": float,
    },
    ...
}
```

```python
get_policy_summary(policy: str = "default") -> Dict[str, Any]
```
Overall policy statistics: `total`, `avg_reward`, `max_reward`, `min_reward`,
`unique_actions`. All computed in Postgres.

### Filtering

```python
get_by_policy(policy: str, limit: int = 100) -> List[RewardMemory]
```
All records for a policy, `ORDER BY reward DESC`.

```python
get_top_rewards(limit: int = 10, policy: str = "default") -> List[RewardMemory]
```
Highest-reward entries for a policy.

### State-transition graph

```python
record_transition(from_id: str, to_id: str, action: str) -> None
```
Insert a `memory_relations` edge: "taking `action` in state `from_id` led to state `to_id`."

```python
get_successor_states(memory_id: str) -> List[Dict[str, Any]]
```
ArangoDB OUTBOUND traversal: all reward state nodes reachable from this one.

---

## Data models

**File:** [`agentic_memory/models.py`](../agentic_memory/models.py)

### `BaseMemory`

```python
@dataclass
class BaseMemory:
    id: str                           # UUID4, auto-generated
    content: str = ""
    metadata: Dict[str, Any] = {}
    embedding: Optional[List[float]]  # set on first store(), not repr'd
    created_at: datetime              # utcnow() on creation
    score: Optional[float] = None     # cosine similarity score, set on search()
```

### `EpisodicMemory(BaseMemory)`

```python
session_id: str = ""
agent_id: str = ""
context: Dict[str, Any] = {}
outcome: Outcome = Outcome.UNKNOWN     # SUCCESS | FAILURE | NEUTRAL | UNKNOWN
importance: float = 0.5               # 0.0 – 1.0
```

### `SemanticMemory(BaseMemory)`

```python
subject: str = ""
predicate: str = ""
object: str = ""
confidence: float = 1.0
source: str = ""
updated_at: Optional[datetime] = None
```

### `ProceduralMemory(BaseMemory)`

```python
name: str = ""
trigger_conditions: List[str] = []
steps: List[ProcedureStep] = []
success_rate: float = 0.0
use_count: int = 0
updated_at: Optional[datetime] = None
```

### `ProcedureStep`

```python
@dataclass
class ProcedureStep:
    step_order: int = 0
    action: str = ""
    parameters: Dict[str, Any] = {}
    expected_outcome: str = ""
```

### `ReflectiveMemory(BaseMemory)`

```python
source_episode_id: Optional[str] = None
lesson: str = ""
improvement_suggestion: str = ""
confidence: float = 1.0
applied_count: int = 0
```

### `RewardMemory(BaseMemory)`

```python
state_description: str = ""
action: str = ""
reward: float = 0.0
outcome: str = ""
policy: str = "default"
context: Dict[str, Any] = {}
```

### `Outcome` enum

```python
class Outcome(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    NEUTRAL = "neutral"
    UNKNOWN = "unknown"
```

### `MemoryType` enum

```python
class MemoryType(str, Enum):
    EPISODIC    = "episodic"
    SEMANTIC    = "semantic"
    PROCEDURAL  = "procedural"
    REFLECTIVE  = "reflective"
    REWARD      = "reward"
```

---

## Configuration

**File:** [`agentic_memory/config.py`](../agentic_memory/config.py)

```python
@dataclass
class WeaviateConfig:
    host: str = "localhost"
    port: int = 8080
    grpc_port: int = 50051
    collection_prefix: str = "AgentMemory"
    embedding_dim: int = 1536

@dataclass
class ArangoConfig:
    url: str = "http://localhost:8529"
    username: str = "root"
    password: str = ""
    database: str = "agent_memory"

@dataclass
class PostgresConfig:
    host: str = "localhost"
    port: int = 5432
    database: str = "agent_memory"
    username: str = "postgres"
    password: str = ""

@dataclass
class MemoryConfig:
    weaviate: WeaviateConfig = WeaviateConfig()
    arango: ArangoConfig = ArangoConfig()
    postgres: PostgresConfig = PostgresConfig()
    embedding_model: str = "all-MiniLM-L6-v2"
    top_k: int = 5
```
