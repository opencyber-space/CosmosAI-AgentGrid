# Memory Types — Concepts

`agentic-memory` models five cognitively-distinct kinds of knowledge that intelligent agents need.
Each type captures something fundamentally different — not just a different data shape, but a
different *relationship between the agent and what it knows*.

---

## 1. Episodic Memory — "What happened?"

### What it is

Memory of specific events bound to a point in time and context. This is the agent's diary —
raw, timestamped experiences tagged with *who was involved, what happened, and how it turned out*.

### Key fields

| Field | Type | Meaning |
|---|---|---|
| `session_id` | str | Which conversation or session this belongs to |
| `agent_id` | str | Which agent recorded it |
| `context` | dict | Free-form: location, user, task, environmental state |
| `outcome` | Outcome enum | `SUCCESS / FAILURE / NEUTRAL / UNKNOWN` |
| `importance` | float 0–1 | How significant this episode was |

### Human analogy

"Last Tuesday I tried to book a flight and the payment failed." The memory is concrete,
singular, and time-anchored — not a general rule, not a skill, just a specific thing that happened.

### Why agents need it

Without episodic memory every session starts cold. With it, an agent can recall prior
interactions, recognize recurring patterns per user or session, and learn from past failures
without re-experiencing them.

### What it enables (beyond basic storage)

- Filter by `session_id` to reconstruct a full conversation thread
- Filter by `outcome` to find all past failures for a task type
- Filter by `importance` to prioritize high-value memories for summarization
- Link episodes to each other via ArangoDB edges (causal chains, follow-ups)
- Link episodes to the reflections they generated (provenance trail)

---

## 2. Semantic Memory — "What is true?"

### What it is

A structured knowledge base of facts stored as **subject → predicate → object** triples —
the standard form of a knowledge graph. This is the agent's world model: context-free truths
that do not belong to any specific event and do not decay with time.

### Key fields

| Field | Type | Meaning |
|---|---|---|
| `subject` | str | The entity the fact is about |
| `predicate` | str | The relationship or property |
| `object` | str | The value or connected entity |
| `confidence` | float 0–1 | How certain the agent is about this fact |
| `source` | str | Where the fact came from |

### Human analogy

"Water boils at 100°C." "Paris is the capital of France." These are not memories of a specific
moment — they are stable facts that survive independently of any particular experience.

### Why agents need it

Agents operating in complex domains need grounded factual knowledge that persists across sessions
and can be queried relationally. Semantic memory answers questions like "What do I know about
Paris?" or "What entities are connected to Einstein?" without replaying experiences.

### What it enables (beyond basic storage)

- Triple lookup: find all facts about a subject, all facts using a predicate, or a specific triple
- Confidence filtering: only use facts above a certainty threshold
- Knowledge graph traversal: find the shortest path between two entities
- Neighbour lookup: what concepts are directly connected to X?
- Auto-construction: storing a fact automatically creates entity nodes and the edge between them

---

## 3. Procedural Memory — "How do I do this?"

### What it is

Memory of *skills* — named, ordered sequences of actions with trigger conditions. This is
know-how rather than know-what. Each procedure is a reusable recipe the agent can recognise
by description and apply step-by-step.

### Key fields

| Field | Type | Meaning |
|---|---|---|
| `name` | str | Human-readable skill name |
| `trigger_conditions` | list[str] | Natural language descriptions of when to apply this |
| `steps` | list[ProcedureStep] | Ordered `{action, parameters, expected_outcome}` |
| `success_rate` | float 0–1 | Rolling average across all recorded executions |
| `use_count` | int | Total times this procedure has been executed |

### Human analogy

A surgeon "knowing how to perform an appendectomy" — it is muscle memory / skill, not a
specific event ("last Thursday I performed one") and not an abstract fact ("appendectomies
remove the appendix"). It is a *procedure*: step 1, step 2, step 3.

### Why agents need it

Agents often face recurring task patterns. Procedural memory lets them store and retrieve
workflows by semantic similarity ("I need to send a report" matches `send_email`), then track
whether that skill actually works via its rolling success rate.

### What it enables (beyond basic storage)

- Search by trigger condition (semantic match, not exact string)
- `record_execution(success)` — updates rolling success rate automatically
- `get_top_procedures()` — find the most reliable skills for a given domain
- `get_by_name()` — fetch a known skill by exact name
- Steps are stored relationally (separate table with FK) and always retrieved in order

---

## 4. Reflective Memory — "What did I learn from this?"

### What it is

Self-generated insights and lessons distilled from past experience. Unlike episodic memory
(raw events), reflective memory is the agent's *interpretation* of those events — metacognition
turned into stored, reusable knowledge.

### Key fields

| Field | Type | Meaning |
|---|---|---|
| `lesson` | str | The distilled, actionable insight |
| `improvement_suggestion` | str | Specific change to make to future behavior |
| `source_episode_id` | str | The episode that generated this reflection |
| `confidence` | float 0–1 | How certain the agent is about this lesson |
| `applied_count` | int | How many times this reflection has influenced a decision |

### Human analogy

After failing at a task, thinking "I should have asked for clarification first." That
meta-observation — generated *by the person*, not recorded from external events — is the
reflection. It changes future behavior without being a procedure (no fixed steps) or a fact
(it is not universally true, just true for this agent in this context).

### Why agents need it

Episodic memories accumulate endlessly. Reflective memory is the compression layer — extracting
durable, actionable lessons so the agent does not have to re-examine every past failure.
`applied_count` makes this the one memory type that measures its own *influence*.

### What it enables (beyond basic storage)

- `mark_applied()` — increment influence counter each time this lesson affects a decision
- Link back to source episodes (ArangoDB `episode_reflection` edge preserves provenance)
- `get_most_applied()` — find the lessons that have most shaped the agent's behavior
- `get_from_episode()` — what did the agent learn from a specific event?
- Confidence filtering for high-certainty lessons only

---

## 5. Reward Memory — "What works best?"

### What it is

Reinforcement-learning-style **(state, action, reward)** tuples. Each record says: "When I was
in *this state* and took *this action*, I received *this reward*." The store can then recommend
the best action for a new state by finding similar past states.

### Key fields

| Field | Type | Meaning |
|---|---|---|
| `state_description` | str | Natural language description of the situation |
| `action` | str | What the agent did |
| `reward` | float | Numeric outcome signal (positive = good, negative = bad) |
| `outcome` | str | Optional descriptive outcome label |
| `policy` | str | Named strategy grouping (multiple policies can coexist) |
| `context` | dict | Additional state information |

### Human analogy

A child learning that "when I am hungry and ask politely, I get food (+1)" vs.
"when I demand it, I get scolded (−1)." Over repeated experience, the reward signal
shapes future behavior in similar situations — not via a rule, but via accumulated evidence.

### Why agents need it

While reflective memory captures *qualitative* lessons, reward memory captures *quantitative*
feedback. It enables behavior shaped by empirical results rather than explicit rules, and
supports multi-policy learning (an agent can maintain separate reward spaces for different
behavioral objectives).

### What it enables (beyond basic storage)

- `get_best_action(state)` — vector search for similar states, returns the action with the highest average reward
- `get_action_stats(policy)` — per-action count/avg/max/min reward from Postgres aggregates
- `get_policy_summary(policy)` — overall statistics for a named policy
- `record_transition(from_id, to_id, action)` — build a state-transition graph in ArangoDB
- `get_successor_states()` — traverse reachable states from a given state

---

## 6. Context KV Memory — "What is the current state of this session?"

### What it is

A scoped, schema-free key-value store backed by Redis. Each entry is identified by a
composite key `{agent_id}__{session_id}__{key}` and holds an arbitrary dict serialised
as JSON. Unlike the five cognitive memory types, `ContextKVMemory` is not about learning
or long-term retention — it is an **active scratchpad** for in-flight agent state.

### Key fields (composite key)

| Component | Meaning |
|---|---|
| `agent_id` | Which agent owns this entry |
| `session_id` | Which conversation or task run |
| `key` | Logical name for the piece of state |
| `data` | Arbitrary `dict` — serialised as JSON in Redis |

### Human analogy

Post-it notes stuck to the desk during a work session. They capture the current step,
temporary decisions, and scratchpad notes — not memories of past events, not learned facts,
just live working state that the agent needs to access repeatedly within a session.

### Why agents need it

The five cognitive memory types are write-once, persist forever, and go through an
embedding pipeline. `ContextKVMemory` is the opposite: cheap O(1) reads and writes,
no embeddings, and naturally scoped to a session. It is the right store for:

- Active task state (`current_step`, `retry_count`, `last_tool_called`)
- Per-session user preferences or decisions
- Cross-call scratch data that does not belong in long-term memory

### What it enables

- `set(agent_id, session_id, key, data)` — store or overwrite any dict
- `get(agent_id, session_id, key)` — retrieve it; returns `None` if absent
- Namespace isolation: two agents in the same session or the same agent in different sessions never collide

---

## How the types relate

```
Raw experience
      │
      ▼
 [Episodic]  ──generates──►  [Reflective]   (ArangoDB episode_reflection edge)
      │                            │
      │                     distils lessons
      │
      ▼
  [Reward]   ──scores actions──►  informs future procedure selection
      │
      ▼
[Procedural] ──named skills triggered by context──►  actions taken
      │
      ▼
 [Semantic]  ──world-model facts that ground all reasoning──►  stable knowledge


[ContextKV]  ──live scratchpad scoped to agent + session──►  ephemeral working state
```

| Type | Backend | Decays? | Self-updates? | Measures influence? |
|---|---|---|---|---|
| Episodic | Postgres / Weaviate / Arango | By importance | No | No |
| Semantic | Postgres / Weaviate / Arango | No | On `update()` | No |
| Procedural | Postgres / Weaviate / Arango | No | `success_rate` rolling avg | Via `use_count` |
| Reflective | Postgres / Weaviate / Arango | No | On `update()` | Yes — `applied_count` |
| Reward | Postgres / Weaviate / Arango | No | Accumulates samples | Via `reward` signal |
| ContextKV | Redis only | No (TTL optional) | On each `set()` | No |
