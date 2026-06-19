"""
OpenAI embeddings example.

Shows two ways to use OpenAI embeddings with AgentMemory:

  1. Default EmbeddingProvider  — uses OpenAI out of the box
  2. Custom embed_fn callback   — wrap any embedding function you like

Prerequisites:
    pip install openai
    export OPENAI_API_KEY=sk-...

Run:
    python examples/example_openai_embeddings.py
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
from agentic_memory.embeddings import EmbeddingProvider

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

from agentic_memory.agent_memory import AgentMemory



# ── Option 1: default EmbeddingProvider (OpenAI) ────────────────────────────

def demo_openai_provider():
    print("=== EmbeddingProvider (OpenAI) ===")
    cfg = make_config()
    embedder = EmbeddingProvider(
        model="text-embedding-3-small",
        api_key=OPENAI_API_KEY,
    )

    with AgentMemory(cfg, embedder=embedder) as mem:
        e1 = mem.remember_episode(
            "User asked for a code review on their Python project.",
            session_id="s-openai-1",
            agent_id="code-agent",
            outcome=Outcome.SUCCESS,
            importance=0.7,
        )
        s1 = mem.know_fact("Python", "is_a", "programming language", confidence=1.0)

        results = mem.recall("programming review assistance")
        for kind, items in results.items():
            if items:
                print(f"  [{kind}] top hit: {items[0].content[:60]}")

        # ── Delete all the memory created ─────────────────────────────
        mem.episodic.delete(e1.id)
        mem.semantic.delete(s1.id)
        print(f"\n\nDeleted episodes: {e1.id}, {s1.id}")


# ── Option 2: custom embed_fn callback ──────────────────────────────────────

def demo_custom_callback():
    print("\n=== Custom embed_fn callback ===")

    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY)

    def my_embed(text: str):
        resp = client.embeddings.create(model="text-embedding-3-small", input=text)
        return resp.data[0].embedding

    cfg = make_config()
    embedder = EmbeddingProvider(embed_fn=my_embed, dim=1536)

    with AgentMemory(cfg, embedder=embedder) as mem:
        r1 = mem.reflect(
            content="OpenAI embeddings capture richer semantic relationships.",
            lesson="Use domain-tuned embeddings for specialised agents.",
            confidence=0.85,
        )
        results = mem.reflective.search("embedding model quality", top_k=2)
        for ref in results:
            print(f"  score={ref.score:.3f}  lesson={ref.lesson[:60]}")

        # ── Delete all the memory created ─────────────────────────────
        mem.reflective.delete(r1.id)
        print(f"\n\nDeleted episodes: {r1.id}")


if __name__ == "__main__":
    demo_openai_provider()
    demo_custom_callback()
