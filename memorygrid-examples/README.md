# agentic-memory

Five-type agentic memory library backed by **Weaviate**, **ArangoDB**, and **PostgreSQL**.

Gives AI agents a structured, queryable, and semantically-searchable memory system that spans
five cognitively-distinct memory types — episodic, semantic, procedural, reflective, and reward.

---

## Memory types at a glance

| Type | Question answered | Primary use |
|---|---|---|
| **Episodic** | What happened? | Time-bound events, session logs |
| **Semantic** | What is true? | Knowledge graph facts (subject–predicate–object) |
| **Procedural** | How do I do this? | Named skills with ordered steps |
| **Reflective** | What did I learn? | Self-generated insights from past experience |
| **Reward** | What works best? | Reinforcement-style (state, action, reward) tuples |

---

## Architecture

Every memory record is written to all three backends simultaneously:

```
store(memory)
     │
     ├──► PostgreSQL   structured data, exact lookups, filters, aggregates
     ├──► Weaviate     384-dim embeddings, cosine similarity search
     └──► ArangoDB     graph nodes + edges, relationship traversal
```

Reads use the most appropriate backend per query type:

- `retrieve(id)` → Postgres (exact primary-key lookup)
- `search(query)` → Weaviate (vector similarity) then Postgres (hydration)
- Graph queries → ArangoDB AQL traversal

---

## Requirements

- Python ≥ 3.8
- PostgreSQL 14+
- Weaviate 1.25+ (standalone)
- ArangoDB 3.10+

---

## Installation

```bash
pip install -e ".[dev]"
```

Dependencies: `weaviate-client>=4.0`, `python-arango>=8.0`, `psycopg2>=2.9`, `sentence-transformers>=3.0`

---

## Quick start

```python
from agentic_memory import AgentMemory
from agentic_memory.models import Outcome

with AgentMemory() as mem:
    # Store an event
    ep = mem.remember_episode(
        "User asked about the weather in Paris",
        session_id="sess-001",
        outcome=Outcome.SUCCESS,
        importance=0.8,
    )

    # Store a knowledge fact
    mem.know_fact("Paris", "is_capital_of", "France")

    # Store a skill
    proc = mem.learn_procedure(
        "send_email",
        steps=[
            {"action": "compose", "parameters": {"to": "..."}, "expected_outcome": "draft ready"},
            {"action": "send",    "parameters": {},             "expected_outcome": "email sent"},
        ],
        trigger_conditions=["user wants to send an email"],
    )

    # Store a self-generated insight
    ref = mem.reflect(
        "I should confirm location before giving weather",
        lesson="Clarify ambiguous location references",
        source_episode_id=ep.id,
    )

    # Record a reward signal
    mem.record_reward("low battery warning shown", "recharge_now", reward=1.0, policy="energy")

    # Search across all five types at once
    results = mem.recall("weather questions", top_k=5)
    # → {"episodic": [...], "semantic": [...], "procedural": [...],
    #    "reflective": [...], "reward": [...]}

    # Access individual stores for richer APIs
    mem.episodic.get_by_session("sess-001")
    mem.semantic.get_neighbors("Paris")
    mem.procedural.record_execution(proc.id, success=True)
    mem.reflective.mark_applied(ref.id)
    mem.reward.get_best_action("low battery warning", policy="energy")
```

---

## Configuration

```python
from agentic_memory.config import MemoryConfig, WeaviateConfig, ArangoConfig, PostgresConfig

config = MemoryConfig(
    weaviate=WeaviateConfig(host="localhost", port=8080),
    arango=ArangoConfig(url="http://localhost:8529", password="password"),
    postgres=PostgresConfig(host="localhost", password="postgres"),
    embedding_model="all-MiniLM-L6-v2",
    top_k=5,
)
mem = AgentMemory(config)
```

All fields default to `localhost` with standard ports. `AgentMemory()` with no arguments
connects to localhost on default ports.

---

## Documentation

| File | Contents |
|---|---|
| [docs/concepts.md](docs/concepts.md) | What each memory type represents and why it exists |
| [docs/implementation.md](docs/implementation.md) | How each type is implemented across the three backends |
| [docs/api-reference.md](docs/api-reference.md) | Full method reference for `AgentMemory` and all five stores |
| [docs/deployment.md](docs/deployment.md) | Kubernetes deployment guide for all three databases |

---

## Project layout

```
agentic_memory/
├── agent_memory.py          # AgentMemory — unified façade
├── models.py                # Dataclasses: BaseMemory + five subtypes
├── config.py                # MemoryConfig, WeaviateConfig, ArangoConfig, PostgresConfig
├── embeddings.py            # EmbeddingProvider (sentence-transformers + mock fallback)
├── memory_types/
│   ├── base.py              # BaseMemoryStore (abstract: store/retrieve/search/update/delete)
│   ├── episodic.py
│   ├── semantic.py
│   ├── procedural.py
│   ├── reflective.py
│   └── reward.py
└── backends/
    ├── postgres_client.py   # PostgresClient + full DDL schema
    ├── weaviate_client.py   # WeaviateClient (HNSW, COSINE)
    └── arango_client.py     # ArangoBackend + AQL traversal

k8s/
├── pv-pvc.yaml              # PersistentVolumes and PersistentVolumeClaims
├── postgres.yaml            # StatefulSet + NodePort Service
├── arango.yaml              # StatefulSet + NodePort Service
└── weaviate.yaml            # StatefulSet + NodePort Service

tests/
├── conftest.py
├── test_agent_memory.py
├── test_episodic.py
├── test_semantic.py
├── test_procedural.py
├── test_reflective.py
└── test_reward.py
```

---

## To Run Examples(Standalone Sample codes)
- Install the requirements.txt 
```bash
pip3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cd examples
python3 example_episodic.py

```

## Running tests

```bash
pytest
```

Tests mock all three backends. `EmbeddingProvider` falls back to a deterministic
mock embedder when `sentence-transformers` is not installed, so tests run without GPU or model downloads.
