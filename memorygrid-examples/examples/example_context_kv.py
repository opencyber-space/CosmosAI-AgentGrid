"""
ContextKVMemory example — connecting to real Redis.

ContextKVMemory is a simple key-value store scoped to an agent and session.
It supports:
  - set(agent_id, session_id, key, data)  — serialize a dict and store it
  - get(agent_id, session_id, key)         — retrieve and deserialize it

The Redis key is composed as "{agent_id}__{session_id}__{key}".

Run:
    python examples/example_context_kv.py
"""
import os,sys
from db_config import make_config

lib_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if lib_dir not in sys.path:
    sys.path.insert(0, lib_dir)
from agentic_memory.backends.redis_client import RedisClient
# ContextKVMemory can also be accessed via AgentMemory.context_kv
from agentic_memory.memory_types.context_kv import ContextKVMemory

from dotenv import load_dotenv
# Find .env by walking up to the directory containing .git
def find_git_root(path):
    current = os.path.abspath(path)
    while True:
        if os.path.exists(os.path.join(current, '.git')):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent

_git_root = find_git_root(__file__)
if _git_root:
    load_dotenv(os.path.join(_git_root, '.env'))
else:
    load_dotenv()

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

def main():
    cfg = make_config()
    redis = RedisClient(cfg.redis)
    
    kv = ContextKVMemory(redis)

    agent_id = "planner-agent"
    session_id = "session-99"

    # ── Store context entries ───────────────────────────────────────────
    kv.set(agent_id, session_id, "user_prefs", {
        "language": "en",
        "timezone": "UTC+5:30",
        "theme": "dark",
    })
    kv.set(agent_id, session_id, "task_state", {
        "current_step": 2,
        "total_steps": 5,
        "last_action": "fetch_data",
        "completed": False,
    })
    kv.set(agent_id, session_id, "scratch", {
        "notes": ["Check quota before retrying", "User prefers concise replies"],
    })
    print(f"Stored 3 keys under agent={agent_id!r} session={session_id!r}")

    # ── Retrieve ────────────────────────────────────────────────────────
    print("\n[get] user_prefs:")
    prefs = kv.get(agent_id, session_id, "user_prefs")
    for k, v in prefs.items():
        print(f"  {k}: {v}")

    print("\n[get] task_state:")
    state = kv.get(agent_id, session_id, "task_state")
    for k, v in state.items():
        print(f"  {k}: {v}")

    # ── Update an existing key ──────────────────────────────────────────
    state["current_step"] = 3
    state["last_action"] = "validate_output"
    kv.set(agent_id, session_id, "task_state", state)
    print("\n[updated] task_state.current_step ->", kv.get(agent_id, session_id, "task_state")["current_step"])

    # ── Missing key returns None ────────────────────────────────────────
    missing = kv.get(agent_id, session_id, "nonexistent_key")
    print(f"\n[get] nonexistent_key -> {missing}")

    # ── Delete a key ──────────────────────────────────────────────────────
    kv.delete(agent_id, session_id, "user_prefs")
    print("\n[deleted] user_prefs")
    kv.delete(agent_id, session_id, "task_state")
    print("\n[deleted] task_state")
    kv.delete(agent_id, session_id, "scratch")
    print("\n[deleted] scratch")

    redis.close()


if __name__ == "__main__":
    main()
