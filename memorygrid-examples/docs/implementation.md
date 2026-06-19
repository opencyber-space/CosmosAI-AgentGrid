# Technical Implementation

This document explains exactly how each memory type is implemented across the three backends —
PostgreSQL, Weaviate, and ArangoDB — including schema, data flow, and per-type design decisions.

---

## Backend overview

`agentic-memory` uses four backends. The five cognitive memory types follow the three-backend
pattern below. `ContextKVMemory` is an exception — it writes only to Redis.

### The three-backend pattern

Every `store()` call on the five cognitive types writes to all three backends. This is not
redundancy — each backend serves a distinct retrieval role.

```
store(memory)
     │
     ├──► PostgreSQL   structured data, exact lookups, filters, aggregates
     ├──► Weaviate     (id, embedding) pairs — semantic similarity search
     └──► ArangoDB     graph nodes + edges — relationship traversal
```

Reads use the most appropriate backend per query type:

```
search(query)                        retrieve(id)
     │                                    │
     ▼                                    ▼
embed(query) → 384-dim vector       Postgres: SELECT * WHERE id = ?
Weaviate: cosine search → (id, score) deserialise row → dataclass
for each id: Postgres.retrieve()
attach score → return list
```

ArangoDB is never queried on the read hot-path — only for graph-specific operations
(neighbours, paths, edges).

---

## Data flow on `store()` — step by step

```python
mem.remember_episode("User asked about Paris weather", session_id="s1", importance=0.9)
```

```
1.  EpisodicMemory dataclass created
    id = uuid4(), created_at = utcnow(), defaults filled

2.  EmbeddingProvider.embed("User asked about Paris weather")
    → sentence-transformers encodes text
    → 384-dim float list, L2-normalised to unit length
    → stored in memory.embedding

3.  PostgresClient.execute(INSERT INTO episodic_memories ...)
    → content, session_id, outcome, importance written as columns
    → context, metadata written as JSONB
    → conn.commit()

4.  WeaviateClient.insert("episodic", memory.id, embedding)
    → collection.data.insert(properties={"memory_id": uuid}, vector=[...1536 floats...])
    → record immediately searchable after insert

5.  ArangoBackend.insert_node("episodic", {_key: uuid, session_id, content, ...})
    → db.collection("episodic_nodes").insert(doc)

6.  return memory.id
```

All three writes are synchronous and independent — there is no distributed transaction
spanning them. If ArangoDB fails after Postgres succeeds, the record exists in Postgres
and Weaviate but not in ArangoDB.

### The single-backend pattern — `ContextKVMemory`

`ContextKVMemory` bypasses the three-backend pattern entirely.

```
set(agent_id, session_id, key, data)
     │
     └──► Redis   JSON-serialised dict at composite key "{agent_id}__{session_id}__{key}"

get(agent_id, session_id, key)
     │
     └──► Redis GET → json.loads() → dict   (None if key absent)
```

There is no embedding, no Postgres row, no ArangoDB node. The design is intentional:
`ContextKVMemory` is a session scratchpad, not a memory substrate — it trades durability
and searchability for constant-time access and zero schema overhead.

---

## Redis backend

**File:** [`backends/redis_client.py`](../agentic_memory/backends/redis_client.py)

A thin wrapper over `redis.Redis` with `decode_responses=True` so all values are
returned as Python strings (not bytes).

```python
class RedisClient:
    def get(self, key: str) -> Optional[str]: ...
    def set(self, key: str, value: str) -> None: ...
    def close(self) -> None: ...
```

`ContextKVMemory` sits on top and owns the JSON encoding/decoding and key composition:

```python
def _key(self, agent_id, session_id, key):
    return f"{agent_id}__{session_id}__{key}"

def set(self, agent_id, session_id, key, data):
    self._redis.set(self._key(...), json.dumps(data))

def get(self, agent_id, session_id, key):
    raw = self._redis.get(self._key(...))
    return json.loads(raw) if raw is not None else None
```

---

## PostgreSQL backend

**File:** [`backends/postgres_client.py`](../agentic_memory/backends/postgres_client.py)

### Schema

Schema is created automatically on first connection via `CREATE TABLE IF NOT EXISTS`.
No migration tool is needed — re-running against an existing database is safe.

```sql
-- Episodic
CREATE TABLE IF NOT EXISTS episodic_memories (
    id          VARCHAR(64)  PRIMARY KEY,
    session_id  VARCHAR(255),
    agent_id    VARCHAR(255),
    content     TEXT         NOT NULL,
    context     JSONB        NOT NULL DEFAULT '{}',
    outcome     VARCHAR(50)  NOT NULL DEFAULT 'unknown',
    importance  FLOAT        NOT NULL DEFAULT 0.5,
    metadata    JSONB        NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Semantic
CREATE TABLE IF NOT EXISTS semantic_memories (
    id          VARCHAR(64)  PRIMARY KEY,
    subject     VARCHAR(500),
    predicate   VARCHAR(255),
    object      TEXT,
    confidence  FLOAT        NOT NULL DEFAULT 1.0,
    source      VARCHAR(500),
    content     TEXT         NOT NULL,
    metadata    JSONB        NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Procedural (parent)
CREATE TABLE IF NOT EXISTS procedures (
    id                  VARCHAR(64)  PRIMARY KEY,
    name                VARCHAR(500) NOT NULL,
    description         TEXT,
    trigger_conditions  JSONB        NOT NULL DEFAULT '[]',
    success_rate        FLOAT        NOT NULL DEFAULT 0.0,
    use_count           INTEGER      NOT NULL DEFAULT 0,
    metadata            JSONB        NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Procedural steps (child, FK cascade)
CREATE TABLE IF NOT EXISTS procedure_steps (
    id               VARCHAR(64)  PRIMARY KEY,
    procedure_id     VARCHAR(64)  NOT NULL REFERENCES procedures(id) ON DELETE CASCADE,
    step_order       INTEGER      NOT NULL,
    action           VARCHAR(500) NOT NULL,
    parameters       JSONB        NOT NULL DEFAULT '{}',
    expected_outcome TEXT,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Reflective
CREATE TABLE IF NOT EXISTS reflective_memories (
    id                      VARCHAR(64)  PRIMARY KEY,
    source_episode_id       VARCHAR(64),
    content                 TEXT         NOT NULL,
    lesson                  TEXT,
    improvement_suggestion  TEXT,
    confidence              FLOAT        NOT NULL DEFAULT 1.0,
    applied_count           INTEGER      NOT NULL DEFAULT 0,
    metadata                JSONB        NOT NULL DEFAULT '{}',
    created_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Reward
CREATE TABLE IF NOT EXISTS reward_memories (
    id                VARCHAR(64)  PRIMARY KEY,
    state_description TEXT         NOT NULL,
    action            VARCHAR(500) NOT NULL,
    reward            FLOAT        NOT NULL,
    outcome           TEXT,
    policy            VARCHAR(255) NOT NULL DEFAULT 'default',
    context           JSONB        NOT NULL DEFAULT '{}',
    metadata          JSONB        NOT NULL DEFAULT '{}',
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
```

### Indices

```sql
CREATE INDEX IF NOT EXISTS idx_episodic_session    ON episodic_memories(session_id);
CREATE INDEX IF NOT EXISTS idx_episodic_agent      ON episodic_memories(agent_id);
CREATE INDEX IF NOT EXISTS idx_episodic_outcome    ON episodic_memories(outcome);
CREATE INDEX IF NOT EXISTS idx_semantic_subject    ON semantic_memories(subject);
CREATE INDEX IF NOT EXISTS idx_semantic_predicate  ON semantic_memories(predicate);
CREATE INDEX IF NOT EXISTS idx_procedure_name      ON procedures(name);
CREATE INDEX IF NOT EXISTS idx_proc_step_proc      ON procedure_steps(procedure_id);
CREATE INDEX IF NOT EXISTS idx_reflective_episode  ON reflective_memories(source_episode_id);
CREATE INDEX IF NOT EXISTS idx_reward_action       ON reward_memories(action);
CREATE INDEX IF NOT EXISTS idx_reward_policy       ON reward_memories(policy);
```

### Access pattern

Uses `psycopg2.extras.RealDictCursor` — every row comes back as a plain `dict`.
No ORM. Each store's `_from_row(row)` method deserialises the dict into a typed dataclass.

```python
# All writes auto-commit
def execute(self, sql, params) -> List[Dict]:
    with self._conn.cursor() as cur:
        cur.execute(sql, params)
        self._conn.commit()
        return [dict(row) for row in cur.fetchall()]
```

---

## Weaviate backend

**File:** [`backends/weaviate_client.py`](../agentic_memory/backends/weaviate_client.py)

### Collections

Five collections are created at init, one per memory type (names must start with uppercase):

```
AgentMemoryEpisodic
AgentMemorySemantic
AgentMemoryProcedural
AgentMemoryReflective
AgentMemoryReward
```

Each collection stores exactly **one property** alongside the vector — only the UUID is
stored in Weaviate; all other data lives in Postgres:

```python
Property(name="memory_id", data_type=DataType.TEXT)
# vector field is managed by Weaviate alongside the object
```

### Index

```python
Configure.VectorIndex.hnsw(distance_metric=VectorDistances.COSINE)
```

HNSW gives sub-linear approximate nearest-neighbour search with high recall.
`Configure.Vectorizer.none()` disables Weaviate's built-in vectorizer — embeddings
are computed by the client and passed directly.

### Search

```python
collection.query.near_vector(
    near_vector=query_embedding,
    limit=top_k,
    return_metadata=MetadataQuery(distance=True),
)
# score = 1.0 - distance  (converts cosine distance to cosine similarity)
# → List[Tuple[str, float]]  — (memory_id, cosine_score)
```

### Update

Weaviate does not support in-place vector mutation. Update is implemented as:

```python
def update(self, memory_type, memory_id, embedding):
    self.delete(memory_type, memory_id)
    self.insert(memory_type, memory_id, embedding)
```

### Why only (memory_id, vector)?

Keeping Weaviate to one property means:
- Weaviate is never the source of truth for any attribute
- Schema changes in any memory type never require a Weaviate migration
- Postgres remains the single authoritative store for structured data

---

## ArangoDB backend

**File:** [`backends/arango_client.py`](../agentic_memory/backends/arango_client.py)

### Collections

Created automatically on init:

**Vertex collections:**

| Name | Stores |
|---|---|
| `episodic_nodes` | Episode nodes |
| `semantic_nodes` | Fact triple nodes |
| `procedural_nodes` | Procedure nodes |
| `reflective_nodes` | Reflection nodes |
| `reward_nodes` | Reward tuple nodes |
| `entity_nodes` | Knowledge graph entity nodes (auto-created by semantic store) |

**Edge collections:**

| Name | Connects | Created by |
|---|---|---|
| `memory_relations` | episodic↔episodic, reward↔reward | `link_episodes()`, `record_transition()` |
| `entity_relations` | entity → entity | `semantic.store()` (automatic) |
| `episode_reflection` | episodic → reflective | `reflective.store()` (when `source_episode_id` set) |

### Graph traversal via AQL

```python
# get_related() — BFS, configurable direction and depth
aql = f"""
FOR v IN 1..{depth} {direction} '{vertex_col}/{key}'
    {edge_col}
RETURN v
"""

# find_entity_path() — shortest path between two knowledge graph entities
aql = """
FOR path IN OUTBOUND SHORTEST_PATH
    CONCAT('entity_nodes/', @from) TO CONCAT('entity_nodes/', @to)
    entity_relations
RETURN path
"""
```

---

## Embedding pipeline

**File:** [`agentic_memory/embeddings.py`](../agentic_memory/embeddings.py)

```python
EmbeddingProvider(model_name="all-MiniLM-L6-v2", dim=384)
```

- Lazy-loads `SentenceTransformer` on first call (avoids startup cost if unused)
- Produces **L2-normalised** unit vectors (required for cosine similarity in Weaviate)
- Falls back to a **deterministic mock** if `sentence-transformers` is not installed:

```python
# Mock: deterministic unit vector seeded by MD5 hash of text
seed = int(hashlib.md5(text.encode()).hexdigest(), 16) % (2 ** 32)
rng = random.Random(seed)
vec = [rng.gauss(0, 1) for _ in range(self.dim)]
norm = sum(x ** 2 for x in vec) ** 0.5 or 1.0
return [x / norm for x in vec]
```

The mock produces the same vector for the same input every time — tests are deterministic
without model downloads or GPU.

### What gets embedded per type

The composite text embedded determines what semantic search retrieves.
Each type embeds more than just `content` so that search captures the meaningful dimensions:

| Type | Embedded text |
|---|---|
| Episodic | `content` |
| Semantic | `subject + predicate + object + content` |
| Procedural | `name + description + join(step.action + step.expected_outcome)` |
| Reflective | `content + lesson + improvement_suggestion` |
| Reward | `state_description + action + outcome` |

---

## Per-type implementation notes

### Episodic

Straightforward three-backend write. `context` and `metadata` are Python dicts serialised
to JSONB via `json.dumps()` on write and deserialized in `_from_row()`.

`link_episodes()` inserts a directed `memory_relations` edge enabling episode chains
(e.g., a follow-up event linked to its cause).

### Semantic

`store()` performs extra work after the standard three-backend write:

```python
self._ensure_entity(memory.subject)    # insert entity node if not present
self._ensure_entity(memory.object)     # insert entity node if not present
self.arango.insert_edge(               # insert knowledge graph edge
    "entity_relations",
    "entity", entity_key(subject),
    "entity", entity_key(object_),
    {"predicate": ..., "confidence": ...},
)
```

Entity keys are `MD5(name)[:16]` — deterministic, collision-resistant for typical entity names.
Duplicate edges are silently swallowed (`except: pass`) since the same subject–predicate–object
triple may be stored multiple times with different confidence scores.

The knowledge graph therefore builds **automatically** as facts are stored — no separate
graph-construction step is required.

### Procedural

Steps are stored in a separate `procedure_steps` table with `ON DELETE CASCADE` —
deleting a procedure automatically deletes all its steps.

`record_execution(success)` computes a rolling average without storing all historical outcomes:

```python
new_rate = (old_rate * old_count + (1.0 if success else 0.0)) / new_count
```

On `update()`, all steps are deleted and re-inserted — partial step update is not supported.

The embedding includes all step text so that `search_by_trigger("send an email")` can
match procedures by their internal step descriptions, not just their name.

### Reflective

`mark_applied()` uses an atomic SQL increment to avoid read-modify-write races:

```python
# Postgres
UPDATE reflective_memories SET applied_count = applied_count + 1 WHERE id = %s

# Then reads back to sync ArangoDB
SELECT applied_count FROM reflective_memories WHERE id = %s
```

If `source_episode_id` is set, `store()` attempts to insert an `episode_reflection` edge.
The `try/except` silently handles cases where the episode node does not yet exist in
ArangoDB (e.g., the episode was stored before ArangoDB was available).

### Reward

`get_best_action()` is the core decision-support method:

```python
def get_best_action(self, state_description, policy="default", top_k=20):
    # 1. Vector search for similar past states
    candidates = self.search(state_description, top_k=20)

    # 2. Filter to matching policy (fall back to all if none match)
    policy_matches = [m for m in candidates if m.policy == policy] or candidates

    # 3. Group by action, compute average reward
    action_rewards: Dict[str, List[float]] = {}
    for mem in policy_matches:
        action_rewards.setdefault(mem.action, []).append(mem.reward)

    # 4. Return action with highest average reward
    best = max(action_rewards, key=lambda a: mean(action_rewards[a]))
    return best, mean(action_rewards[best])
```

`get_action_stats()` delegates all aggregation to Postgres (`GROUP BY action` with
`COUNT / AVG / MAX / MIN`) — never loads raw records into Python for this query.

`record_transition()` builds a state-transition graph: edges in `memory_relations`
where each edge represents "taking action X in state A led to state B."
