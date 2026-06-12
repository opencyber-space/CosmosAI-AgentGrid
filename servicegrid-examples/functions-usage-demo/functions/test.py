import os
import sys
from dotenv import load_dotenv

# Dynamically add the directory 2 folders behind the current folder to sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
two_folders_behind = os.path.abspath(os.path.join(current_dir, '..', '..'))
sys.path.insert(0, two_folders_behind)

try:
    from agents_functions import AgentFunctions
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
FUNCTION_REGISTRY_URL = os.environ.get("FUNCTION_REGISTRY_URL", "")

agent_function = AgentFunctions(
    functions_registry_url=FUNCTION_REGISTRY_URL,
    unique_parameter="b14",
    executor_id="executor-001",
    num_workers=8,
)

agent_function.add("code-validator:1.7.0-stable")
agent_function.add("test-generator:1.10.0-stable")
agent_function.add("test-runner:1.0.0-stable")

# Sample code to analyse
sample_input = {
    "code": "def add(a, b):\n    return a + b",
    "function_name": "add",
    "description": "Adds two numbers and returns the result"
}


# Step 1 — validate the code
print('calling code validator')
result1 = agent_function.call(
    function_id="code-validator:1.7.0-stable",
    input_data={
        **sample_input
    },
    parameters={
            "openai_api_key": OPENAI_API_KEY,
            "model": "gpt-5.4-mini"
        }
)
print("=== code-validator result ===")
print(result1)


# agent_function.remove(function_id="test-case-generator:1.6.0-stable", remove_deployment=True)
# Step 2 — generate test cases (uses sample_input directly, independent of step 1)

print('calling test generator')
result2 = agent_function.call(
    function_id="test-generator:1.10.0-stable",
    input_data={
        **result1
    },
    parameters={
            "openai_api_key": OPENAI_API_KEY,
            "model": "gpt-5.4-mini",
            "num_tests": 5
        }
)
print("\n=== test-case-generator result ===")
print(result2)

# Step 3 — run the generated tests against the code
print("calling test runner")
result3 = agent_function.call(
    function_id="test-runner:1.0.0-stable",
    input_data={
        **result2
    }
)
print("\n=== test-runner result ===")
print(result3)


# Step4 - Remove the add functions
# Do this when  needed, If in case the functions are reasuable by other agents, then better not remove them
print("removing function")
agent_function.remove(function_id="code-validator:1.6.0-stable", remove_deployment=True)
agent_function.remove(function_id="test-generator:1.9.0-stable", remove_deployment=True)
agent_function.remove(function_id="test-runner:1.0.0-stable", remove_deployment=True)
