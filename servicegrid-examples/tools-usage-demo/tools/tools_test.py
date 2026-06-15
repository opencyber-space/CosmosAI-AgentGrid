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

from agents_tools import AgentTools

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

### Unmment below for testing OPENAI LLMs
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_TOOL_MODEL = {
    "llm_type": "openai",
    "llm_block_id": "openai:gpt-5.4-mini",
    "llm_selection_query": {
        "task": "summarization"
    },
    "llm_parameters": {
        "api_key": OPENAI_API_KEY,
        "max_completion_tokens": 4096,
        "top_k": 50,
        "top_p": 0.95,
        "temperature": 0.5
    }
}
which_model_to_use_for_tool = OPENAI_TOOL_MODEL
model_name = "gpt-4o-mini" # this is for search_tool and search_and_execute_tool

### Unmment below for testing GEMINI LLMs
# GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
# GEMINI_TOOL_MODEL = {
#     "llm_type": "gemini",
#     "llm_block_id": "gemini:gemini-2.5-flash",
#     "llm_selection_query": {
#         "task": "summarization"
#     },
#     "llm_parameters": {
#         "api_key": GEMINI_API_KEY,
#         "max_completion_tokens": 4096,
#         "top_k": 50,
#         "top_p": 0.95,
#         "temperature": 0.5
#     }
# }
# which_model_to_use_for_tool = GEMINI_TOOL_MODEL
# model_name = "gemini-2.5-flash" # this is for search_tool and search_and_execute_tool

TOOLS_REGISTRY_URL = os.environ.get("TOOLS_REGISTRY_URL", "")
tools = AgentTools(tools_db_url=TOOLS_REGISTRY_URL, openai_api_key=OPENAI_API_KEY, gemini_api_key=None, model_name=model_name)

# ──────────────────────────────────────────────
# 1. commit-scribe
# ──────────────────────────────────────────────
print("\n=== commit-scribe ===")
tools.add("agentspace.commit-scribe.v4")

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

response = tools.execute_tool_by_id(
    "agentspace.commit-scribe.v4",
    input_data={"diff": diff, "branch_name": "fix/strict-token-validation", "repo_context": "SaaS backend","tool_model": which_model_to_use_for_tool},
)
print(response)

# store the commit type for later inspection
tools.execute_command(
    "agentspace.commit-scribe.v4",
    command="set",
    data={"key": "last_commit_type", "value": response.get("commit_message", {}).get("type")},
)
print(tools.execute_command("agentspace.commit-scribe.v4", command="get", data={"key": "last_commit_type"}))
print(tools.execute_command("agentspace.commit-scribe.v4", command="get_state", data={}))


# # ──────────────────────────────────────────────
# # 2. log-detective
# # ──────────────────────────────────────────────
# print("\n=== log-detective ===")
# tools.add("agentspace.log-detective.v4")

# logs = """\
# 2024-06-10T02:14:01Z INFO  payments-api: request received POST /charge
# 2024-06-10T02:14:01Z ERROR db: connection timeout after 30s (attempt 1/3)
# 2024-06-10T02:14:02Z WARN  payments-api: retrying db connection
# 2024-06-10T02:14:32Z ERROR db: connection timeout after 30s (attempt 2/3)
# 2024-06-10T02:14:33Z ERROR db: connection timeout after 30s (attempt 3/3)
# 2024-06-10T02:14:33Z FATAL payments-api: circuit breaker OPEN — db unreachable
# 2024-06-10T02:14:34Z ERROR payments-api: returning 503 to client
# 2024-06-10T02:14:35Z ERROR payments-api: returning 503 to client
# 2024-06-10T02:14:36Z ERROR payments-api: returning 503 to client
# """

# response = tools.execute_tool_by_id(
#     "agentspace.log-detective.v4",
#     input_data={"logs": logs, "service_name": "payments-api", "time_window": "2024-06-10 02:14 UTC","tool_model": which_model_to_use_for_tool},
# )
# print(response)

# # store severity for downstream use
# tools.execute_command(
#     "agentspace.log-detective.v4",
#     command="set",
#     data={"key": "last_severity", "value": response.get("log_analysis", {}).get("severity_score")},
# )
# print(tools.execute_command("agentspace.log-detective.v4", command="get", data={"key": "last_severity"}))
# print(tools.execute_command("agentspace.log-detective.v4", command="get_state", data={}))


# # ──────────────────────────────────────────────
# # 3. schema-forge (JSON sample)
# # ──────────────────────────────────────────────
# print("\n=== schema-forge (json) ===")
# tools.add("agentspace.schema-forge.v4")

# sample_json = '{"order_id": 1001, "customer_id": 42, "amount": 99.99, "currency": "USD", "status": "paid", "created_at": "2024-06-10T02:00:00Z"}'

# response = tools.execute_tool_by_id(
#     "agentspace.schema-forge.v4",
#     input_data={"sample_data": sample_json, "format": "json", "purpose": "E-commerce order record", "tool_model": which_model_to_use_for_tool},
# )
# print(response)

# # ──────────────────────────────────────────────
# # 3. schema-forge (CSV sample)
# # ──────────────────────────────────────────────
# print("\n=== schema-forge (csv) ===")
# sample_csv = "order_id,customer_id,amount,currency,status\n1001,42,99.99,USD,paid\n1002,17,14.50,EUR,pending"

# response = tools.execute_tool_by_id(
#     "agentspace.schema-forge.v4",
#     input_data={"sample_data": sample_csv, "format": "csv", "purpose": "Order export from reporting DB","tool_model": which_model_to_use_for_tool},
# )
# print(response)

# tools.execute_command(
#     "agentspace.schema-forge.v4",
#     command="set",
#     data={"key": "last_format", "value": response.get("schema_result", {}).get("format_detected")},
# )
# print(tools.execute_command("agentspace.schema-forge.v4", command="get", data={"key": "last_format"}))
# print(tools.execute_command("agentspace.schema-forge.v4", command="get_state", data={}))
