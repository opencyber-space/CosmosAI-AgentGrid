"""
Demonstrates OpenAI-powered tool search and execution via AgentTools.

Two new methods are available when openai_api_key is supplied:

  tools.search_tool(prompt)
      → returns the tool_id of the best match (no execution)

  tools.search_and_execute_tool(prompt, input_dict)
      → selects the tool, auto-formats input_dict against its schema
        via OpenAI function-calling, executes it, and returns the output
"""
import os
import sys
from dotenv import load_dotenv

# Dynamically add the directory 2 folders behind the current folder to sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
two_folders_behind = os.path.abspath(os.path.join(current_dir, '..', '..'))
sys.path.insert(0, two_folders_behind)

try:
    from agents_tools import AgentTools
finally:
    # Clean up sys.path to avoid polluting namespace
    if two_folders_behind in sys.path:
        sys.path.remove(two_folders_behind)



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
model_name = "gpt-4o-mini"

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
model_name = "gemini-2.5-flash"

TOOLS_REGISTRY_URL = os.environ.get("TOOLS_REGISTRY_URL", "")
tools = AgentTools(tools_db_url=TOOLS_REGISTRY_URL, openai_api_key=None, gemini_api_key=GEMINI_API_KEY, model_name="gemini-2.5-flash")


# Register all tools upfront so their runtimes are ready before any search.
tools.add("agentspace.commit-scribe.v4")
tools.add("agentspace.log-detective.v4")
tools.add("agentspace.schema-forge.v4")


# ──────────────────────────────────────────────────────────────────────────────
# 1. search_tool — just identify the right tool, no execution
# ──────────────────────────────────────────────────────────────────────────────

# print("\n=== search_tool: commit message ===")
# tool_id = tools.search_tool(
#     "I need to generate a conventional commit message from a git diff"
# )
# print(f"Selected tool: {tool_id}")

# print("\n=== search_tool: log analysis ===")
# tool_id = tools.search_tool(
#     "Analyse application logs and identify the root cause of the failure"
# )
# print(f"Selected tool: {tool_id}")

# print("\n=== search_tool: schema inference ===")
# tool_id = tools.search_tool(
#     "Infer a JSON schema from a sample data payload"
# )
# print(f"Selected tool: {tool_id}")


# ──────────────────────────────────────────────────────────────────────────────
# 2. search_and_execute_tool — find + format + run in one call
# ──────────────────────────────────────────────────────────────────────────────
# ──────────────────────────────────────────────────────────────────────────────
# 2.1 For Commit Scribe
# ──────────────────────────────────────────────────────────────────────────────
# diff = """\
# diff --git a/auth/login.py b/auth/login.py
# index 3a1f2b4..9c8d1e5 100644
# --- a/auth/login.py
# +++ b/auth/login.py
# @@ -10,6 +10,10 @@ def login(request):
#      token = request.headers.get("Authorization")
# +    if not token:
# +        raise AuthError("missing token")
# +    if len(token) < 32:
# +        raise AuthError("token too short")
#      user = verify_token(token)
#      return user
# """

# print("\n=== search_and_execute_tool: commit-scribe ===")
# response = tools.search_and_execute_tool(
#     prompt="Generate a conventional commit message from this auth fix diff",
#     input_dict={
#         "diff": diff,
#         "branch_name": "fix/strict-token-validation",
#         "repo_context": "SaaS backend",
#     },
# )
# print(response)

# ──────────────────────────────────────────────
# ──────────────────────────────────────────────────────────────────────────────
# 2.2 For Log Detective
# ──────────────────────────────────────────────────────────────────────────────

# logs = """\
# 2024-06-10T02:14:01Z INFO  payments-api: request received POST /charge
# 2024-06-10T02:14:01Z ERROR db: connection timeout after 30s (attempt 1/3)
# 2024-06-10T02:14:02Z WARN  payments-api: retrying db connection
# 2024-06-10T02:14:32Z ERROR db: connection timeout after 30s (attempt 2/3)
# 2024-06-10T02:14:33Z ERROR db: connection timeout after 30s (attempt 3/3)
# 2024-06-10T02:14:33Z FATAL payments-api: circuit breaker OPEN — db unreachable
# 2024-06-10T02:14:34Z ERROR payments-api: returning 503 to client
# """

# print("\n=== search_and_execute_tool: log-detective ===")
# response = tools.search_and_execute_tool(
#     prompt="Analyse these payment service logs and identify the root cause",
#     input_dict={
#         "logs": logs,
#         "service_name": "payments-api",
#         "time_window": "2024-06-10 02:14 UTC",
#     },
# )
# print(response)

# # ──────────────────────────────────────────────
# ──────────────────────────────────────────────────────────────────────────────
# 2.3 For Schema Forge
# ──────────────────────────────────────────────────────────────────────────────

# sample_json = (
#     '{"order_id": 1001, "customer_id": 42, "amount": 99.99, '
#     '"currency": "USD", "status": "paid", "created_at": "2024-06-10T02:00:00Z"}'
# )

# print("\n=== search_and_execute_tool: schema-forge ===")
# response = tools.search_and_execute_tool(
#     prompt="Infer a JSON schema from this e-commerce order record",
#     input_dict={
#         "sample_data": sample_json,
#         "format": "json",
#         "purpose": "E-commerce order record",
#     },
# )
# print(response)

# # ---------------------------Testing Generic Prompt ----------------------------# #

# ──────────────────────────────────────────────────────────────────────────────
# 3. search_and_execute_tool — find + format + run in one call with GENERIC PROMPTS
# ──────────────────────────────────────────────────────────────────────────────
# ──────────────────────────────────────────────────────────────────────────────
# 3.1 For Commit Scribe With Generic Prompt
# ──────────────────────────────────────────────────────────────────────────────

diff = """\
diff --git a/auth/login.py b/auth/login.py
index 3a1f2b4..9c8d1e5 100644
--- a/auth/login.py
+++ b/auth/login.py
@@ -10,6 +10,10 @@ def login(request):
     token = request.headers.get("Authorization")
+    if not token:
+        raise AuthError("missing token")
+    if len(token) < 32:
+        raise AuthError("token too short")
     user = verify_token(token)
     return user
"""

print("\n=== search_and_execute_tool: commit-scribe ===")
response = tools.search_and_execute_tool(
    prompt="What can be done with this data",
    input_dict={
        "input_data": diff
    },
)
print(response)


# ──────────────────────────────────────────────────────────────────────────────
# 3.2 For Log Detective With Generic Prompt
# ──────────────────────────────────────────────────────────────────────────────

# logs = """\
# 2024-06-10T02:14:01Z INFO  payments-api: request received POST /charge
# 2024-06-10T02:14:01Z ERROR db: connection timeout after 30s (attempt 1/3)
# 2024-06-10T02:14:02Z WARN  payments-api: retrying db connection
# 2024-06-10T02:14:32Z ERROR db: connection timeout after 30s (attempt 2/3)
# 2024-06-10T02:14:33Z ERROR db: connection timeout after 30s (attempt 3/3)
# 2024-06-10T02:14:33Z FATAL payments-api: circuit breaker OPEN — db unreachable
# 2024-06-10T02:14:34Z ERROR payments-api: returning 503 to client
# """

# print("\n=== search_and_execute_tool: log-detective ===")
# response = tools.search_and_execute_tool(
#     prompt="What can be done with this data",
#     input_dict={
#         "logs": logs,
#         "service_name": "payments-api",
#         "time_window": "2024-06-10 02:14 UTC",
#     },
# )
# print(response)


# ──────────────────────────────────────────────────────────────────────────────
# 3.3 For Schema Forge With Generic Prompt
# ──────────────────────────────────────────────────────────────────────────────

# sample_json = (
#     '{"order_id": 1001, "customer_id": 42, "amount": 99.99, '
#     '"currency": "USD", "status": "paid", "created_at": "2024-06-10T02:00:00Z"}'
# )

# print("\n=== search_and_execute_tool: schema-forge with format and purpose===")
# response = tools.search_and_execute_tool(
#     prompt="What can be done with this data",
#     input_dict={
#         "input": sample_json,
#         "format": "json",
#         "purpose": "E-commerce order record",
#     },
# )
# print(response)

# ──────────────────────────────────────────────────────────────────────────────
# 3.3 For Schema Forge With Generic Prompt and less input
# ──────────────────────────────────────────────────────────────────────────────

# print("\n=== search_and_execute_tool: schema-forge without format and purpose===")
# response = tools.search_and_execute_tool(
#     prompt="What can be done with this data",
#     input_dict={
#         "input": sample_json
#     },
# )
# print(response)
