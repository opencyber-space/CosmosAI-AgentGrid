"""
Reflective memory example — connecting to real Postgres, Weaviate, and ArangoDB.

Reflective memory stores self-generated lessons extracted from experience.
ArangoDB preserves the provenance link between an episode and the reflection
it generated (episode_reflection edges).

Run:
    python examples/example_reflective.py
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
from agentic_memory.models import Outcome

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
        # ── Store a source episode first ────────────────────────────────
        episode = mem.remember_episode(
            "Agent provided weather forecast using stale cached data from 6 hours ago.",
            session_id="session-77",
            agent_id="weather-agent",
            outcome=Outcome.FAILURE,
            importance=0.85,
        )
        print(f"Source episode: {episode.id}")

        # ── Store reflective memories ────────────────────────────────────
        r1 = mem.reflect(
            content="Providing stale data without warning degrades user trust.",
            lesson="Always check cache freshness before serving forecasts.",
            improvement_suggestion="Add a cache TTL check before responding; if stale, fetch live or warn user.",
            source_episode_id=episode.id,
            confidence=0.95,
        )
        r2 = mem.reflect(
            content="Silent failures are harder to diagnose than explicit errors.",
            lesson="Log all data-source fallbacks explicitly.",
            improvement_suggestion="Emit a structured warning log entry whenever a fallback data source is used.",
            confidence=0.80,
        )
        r3 = mem.reflect(
            content="User satisfaction drops when agents don't acknowledge limitations.",
            lesson="Be transparent about data freshness and uncertainty.",
            improvement_suggestion="Include a freshness timestamp and confidence level in every data response.",
            confidence=0.90,
        )
        print(f"Stored reflections: {r1.id}, {r2.id}, {r3.id}")

        # ── Semantic search ──────────────────────────────────────────────
        print("\n[Search] 'data quality issues':")
        for ref in mem.reflective.search("data quality issues", top_k=3):
            print(f"  score={ref.score:.3f}  lesson={ref.lesson[:60]}")

        # ── Mark applied ─────────────────────────────────────────────────
        mem.reflective.mark_applied(r1.id)
        mem.reflective.mark_applied(r1.id)
        mem.reflective.mark_applied(r3.id)

        # ── Most frequently applied ───────────────────────────────────────
        print("\n[Most applied reflections]:")
        for ref in mem.reflective.get_most_applied(limit=5):
            print(f"  applied={ref.applied_count}  lesson={ref.lesson[:60]}")

        # ── Reflections from a specific episode ──────────────────────────
        print(f"\n[Reflections from episode {episode.id[:8]}...]:")
        for ref in mem.reflective.get_from_episode(episode.id):
            print(f"  {ref.lesson[:70]}")

        # ── ArangoDB provenance graph ─────────────────────────────────────
        print(f"\n[ArangoDB: reflections generated from episode {episode.id[:8]}...]:")
        for node in mem.reflective.get_reflections_for_episode(episode.id):
            print(f"  {node.get('lesson', '')[:70]}")

        # ── High-confidence reflections ───────────────────────────────────
        print("\n[High-confidence >= 0.9]:")
        for ref in mem.reflective.get_above_confidence(threshold=0.9):
            print(f"  confidence={ref.confidence}  {ref.lesson[:60]}")


        # ── Delete all the memory created ─────────────────────────────
        mem.episodic.delete(episode.id)
        mem.reflective.delete(r1.id)
        mem.reflective.delete(r2.id)
        mem.reflective.delete(r3.id)
        print(f"\n\nDeleted episode: {episode.id} and reflections: {r1.id}, {r2.id}, {r3.id}")

if __name__ == "__main__":
    main()
