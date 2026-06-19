"""
Procedural memory example — connecting to real Postgres, Weaviate, and ArangoDB.

Procedural memory stores named skills as ordered step sequences. It tracks
execution success rates and supports trigger-condition search.

Run:
    python examples/example_procedural.py
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
        # ── Store procedures ────────────────────────────────────────────
        send_email = mem.learn_procedure(
            "send_email",
            description="Compose and dispatch an email via the mail API.",
            trigger_conditions=["user requests sending an email", "email draft is ready"],
            steps=[
                {"action": "validate_recipient",  "parameters": {"field": "to"},        "expected_outcome": "valid email address"},
                {"action": "compose_body",         "parameters": {"template": "default"},"expected_outcome": "email body text"},
                {"action": "call_mail_api",        "parameters": {"endpoint": "/send"},  "expected_outcome": "202 Accepted"},
                {"action": "confirm_delivery",     "parameters": {},                      "expected_outcome": "delivery_id returned"},
            ],
        )

        book_flight = mem.learn_procedure(
            "book_flight",
            description="Search available flights and complete a booking.",
            trigger_conditions=["user asks to book a flight", "destination provided"],
            steps=[
                {"action": "search_flights",   "parameters": {"api": "skyscanner"},   "expected_outcome": "list of options"},
                {"action": "select_best_fare", "parameters": {"sort": "price"},        "expected_outcome": "chosen flight id"},
                {"action": "confirm_booking",  "parameters": {"payment": "on_file"},   "expected_outcome": "booking reference"},
                {"action": "send_itinerary",   "parameters": {"via": "email"},         "expected_outcome": "email sent"},
            ],
        )
        print(f"Stored procedures: {send_email.id}, {book_flight.id}")

        # ── Simulate executions ──────────────────────────────────────────
        mem.procedural.record_execution(send_email.id, success=True)
        mem.procedural.record_execution(send_email.id, success=True)
        mem.procedural.record_execution(send_email.id, success=False)
        mem.procedural.record_execution(book_flight.id, success=True)

        # ── Semantic search ──────────────────────────────────────────────
        print("\n[Search] 'send a message to someone':")
        for proc in mem.procedural.search("send a message to someone", top_k=3):
            print(f"  score={proc.score:.3f}  name={proc.name}  steps={len(proc.steps)}")

        # ── Trigger-condition search ──────────────────────────────────────
        print("\n[Trigger search] 'user wants to fly somewhere':")
        for proc in mem.procedural.search_by_trigger("user wants to fly somewhere"):
            print(f"  {proc.name}  triggers={proc.trigger_conditions}")

        # ── Lookup by name ───────────────────────────────────────────────
        fetched = mem.procedural.get_by_name("send_email")
        if fetched:
            updated = mem.procedural.retrieve(send_email.id)
            print(f"\n[send_email stats] use_count={updated.use_count}  success_rate={updated.success_rate:.2f}")
            for s in fetched.steps:
                print(f"  step {s.step_order}: {s.action}")

        # ── Top procedures by success rate ────────────────────────────────
        print("\n[Top procedures by success rate]:")
        for proc in mem.procedural.get_top_procedures(limit=5):
            print(f"  {proc.name}  use_count={proc.use_count}  success_rate={proc.success_rate:.2f}")


        # ── Delete all the memory created ─────────────────────────────
        mem.procedural.delete(send_email.id)
        mem.procedural.delete(book_flight.id)
        print(f"\n\nDeleted procedures: {send_email.id}, {book_flight.id}")

if __name__ == "__main__":
    main()
