"""
Reward memory example — connecting to real Postgres, Weaviate, and ArangoDB.

Reward memory stores (state, action, reward) tuples. The nearest-neighbour
lookup in Weaviate lets the agent surface the best historical action for a
state similar to the current one.

Run:
    python examples/example_reward.py
sudo apt update
sudo apt install git gcc libpq-dev
cd memorygrid-examples/agentic-memory
pip install -e ".[dev]"
# cd memorygrid-examples/fs
# pip install -e ".[dev]"

"""
import os,sys
from db_config import make_config

lib_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if lib_dir not in sys.path:
    sys.path.insert(0, lib_dir)
from agentic_memory.agent_memory import AgentMemory

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

    with AgentMemory(cfg, openai_api_key=OPENAI_API_KEY) as mem:
        # ── Record (state, action, reward) tuples ───────────────────────
        states_actions = [
            ("battery level is critically low",         "recharge_now",        1.0,  "battery restored"),
            ("battery level is critically low",         "continue_task",       -1.0, "device shutdown"),
            ("battery level is critically low",         "recharge_now",        1.0,  "battery restored"),
            ("user is idle for more than 5 minutes",    "send_summary",        0.8,  "user re-engaged"),
            ("user is idle for more than 5 minutes",    "do_nothing",          -0.2, "session timeout"),
            ("external API rate limit reached",         "back_off_60s",        0.9,  "requests resumed"),
            ("external API rate limit reached",         "retry_immediately",   -0.5, "429 error repeated"),
            ("external API rate limit reached",         "back_off_60s",        0.9,  "requests resumed"),
            ("task queue is empty",                     "enter_standby",       0.5,  "resources saved"),
            ("task queue is empty",                     "poll_for_new_tasks",  0.3,  "no tasks found"),
        ]

        ids = []
        for state, action, reward, outcome in states_actions:
            rw = mem.record_reward(state, action, reward, outcome=outcome, policy="default")
            ids.append(rw.id)
        print(f"Stored {len(ids)} reward memories.")

        # ── Record a state transition in ArangoDB ────────────────────────
        mem.reward.record_transition(ids[0], ids[2], action="recharge_now")

        # ── Best action for a similar state ──────────────────────────────
        query_state = "device battery is almost empty"
        result = mem.reward.get_best_action(query_state, policy="default")
        if result:
            action, avg_reward = result
            print(f"\n[Best action] '{query_state}'")
            print(f"  → action='{action}'  avg_reward={avg_reward:.2f}")

        # ── Semantic search over states ──────────────────────────────────
        print("\n[Search] 'API throttled too many requests':")
        for rw in mem.reward.search("API throttled too many requests", top_k=3):
            print(f"  score={rw.score:.3f}  action={rw.action}  reward={rw.reward}")

        # ── Per-action stats ──────────────────────────────────────────────
        print("\n[Action stats for policy=default]:")
        for action, stats in mem.reward.get_action_stats("default").items():
            print(f"  {action:<30} avg={stats['avg_reward']:.2f}  count={stats['count']}")

        # ── Policy summary ────────────────────────────────────────────────
        summary = mem.reward.get_policy_summary("default")
        print(f"\n[Policy summary] total={summary.get('total')}  "
              f"avg_reward={float(summary.get('avg_reward', 0)):.2f}  "
              f"unique_actions={summary.get('unique_actions')}")

        # ── Top rewards ───────────────────────────────────────────────────
        print("\n[Top 3 reward memories]:")
        for rw in mem.reward.get_top_rewards(limit=3):
            print(f"  reward={rw.reward}  action={rw.action}  state={rw.state_description[:50]}")

        # ── Successor states from ArangoDB ───────────────────────────────
        print(f"\n[Successor states of {ids[0][:8]}... from ArangoDB]:")
        for node in mem.reward.get_successor_states(ids[0]):
            print(f"  action={node.get('action')}  state={node.get('state_description', '')[:50]}")


        # ── Delete all the memory created ─────────────────────────────
        for r_id in ids:
            mem.reward.delete(r_id)
            print(f"\n\nDeleted rewards: {r_id}")

if __name__ == "__main__":
    main()
