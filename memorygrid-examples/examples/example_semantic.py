"""
Semantic memory example — connecting to real Postgres, Weaviate, and ArangoDB.

Semantic memory stores factual knowledge as subject–predicate–object triples and
builds a knowledge graph in ArangoDB for path-finding between concepts.

Run:
    python examples/example_semantic.py
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
        # ── Store facts as triples ──────────────────────────────────────
        s1 = mem.know_fact("Paris",          "is_capital_of",   "France",         confidence=1.0)
        s2 = mem.know_fact("France",         "is_member_of",    "European Union", confidence=1.0)
        s3 = mem.know_fact("Eiffel Tower",   "is_located_in",   "Paris",          confidence=1.0)
        s4 = mem.know_fact("Louvre Museum",  "is_located_in",   "Paris",          confidence=1.0)
        s5 = mem.know_fact("Seine",          "flows_through",   "Paris",          confidence=1.0)
        s6 = mem.know_fact("Napoleon",       "was_born_in",     "Corsica",        confidence=1.0,
                      source="encyclopedia")
        s7 = mem.know_fact("Corsica",        "is_part_of",      "France",         confidence=1.0)
        print("Facts stored.")

        # ── Semantic similarity search ──────────────────────────────────
        print("\n[Semantic search] 'European capital famous landmarks':")
        for fact in mem.semantic.search("European capital famous landmarks", top_k=3):
            print(f"  score={fact.score:.3f}  {fact.subject} {fact.predicate} {fact.object}")

        # ── Triple lookup ────────────────────────────────────────────────
        print("\n[get_by_subject] 'Paris':")
        for fact in mem.semantic.get_by_subject("Paris"):
            print(f"  {fact.subject} {fact.predicate} {fact.object}  (confidence={fact.confidence})")

        # ── Exact triple fetch ───────────────────────────────────────────
        triple = mem.semantic.get_triple("Paris", "is_capital_of")
        if triple:
            print(f"\n[get_triple] Paris is_capital_of → {triple.object}")

        # ── Knowledge-graph neighbours ───────────────────────────────────
        print("\n[KG neighbours of Paris (OUTBOUND)]:")
        for node in mem.semantic.get_neighbors("Paris", direction="OUTBOUND"):
            print(f"  → {node.get('name', node.get('_key'))}")

        # ── Shortest path ─────────────────────────────────────────────────
        print("\n[KG path] Napoleon → European Union:")
        path = mem.semantic.find_path("Napoleon", "European Union")
        for step in path:
            print(f"  {step}")


        # ── Delete all the memory created ─────────────────────────────
        mem.semantic.delete(s1.id)
        mem.semantic.delete(s2.id)
        mem.semantic.delete(s3.id)
        mem.semantic.delete(s4.id)
        mem.semantic.delete(s5.id)
        mem.semantic.delete(s6.id)
        mem.semantic.delete(s7.id)
        print(f"\n\nDeleted facts: {s1.id}, {s2.id}, {s3.id}, {s4.id}, {s5.id}, {s6.id}, {s7.id}")

if __name__ == "__main__":
    main()
