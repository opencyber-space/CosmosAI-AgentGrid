import os
import sys
import json
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

FUNCTION_REGISTRY_URL = os.environ.get("FUNCTION_REGISTRY_URL", "")

agent_function = AgentFunctions(
    functions_registry_url=FUNCTION_REGISTRY_URL,
    unique_parameter="ac23",
    executor_id="executor-001",
    num_workers=8,
)

# Helper to load function ID from its relative function.json path
def load_function_id(relative_path):
    json_path = os.path.join(current_dir, relative_path)
    with open(json_path, 'r') as f:
        data = json.load(f)
    return f"{data['function_name']}:{data['function_version']}-{data['function_release_tag']}"

code_validator_id = load_function_id("functions/code-validator/function.json")
test_generator_id = load_function_id("functions/test-case-generator/function.json")
test_runner_id = load_function_id("functions/test-runner/function.json")

agent_function.add(code_validator_id)
agent_function.add(test_generator_id)
agent_function.add(test_runner_id)

# Sample code to analyse
sample_input = {
    "code": "def add(a, b):\n    return a + b",
    "function_name": "add",
    "description": "Adds two numbers and returns the result"
}


# Step 1 — validate the code
print('calling code validator')
result1 = agent_function.call(
    function_id=code_validator_id,
    input_data={
        **sample_input
    },
    parameters={
            "openai_api_key": OPENAI_API_KEY,
            "model": "gpt-5.4-mini",
            "tool_model": which_model_to_use_for_tool
        }
)
print("=== code-validator result ===")
print(result1)


# Step 2 — generate test cases (uses sample_input directly, independent of step 1)
print('calling test generator')
result2 = agent_function.call(
    function_id=test_generator_id,
    input_data={
        **result1
    },
    parameters={
            "openai_api_key": OPENAI_API_KEY,
            "model": "gpt-5.4-mini",
            "num_tests": 5,
            "tool_model": which_model_to_use_for_tool
        }
)
print("\n=== test-case-generator result ===")
print(result2)

# Step 3 — run the generated tests against the code
print("calling test runner")
result3 = agent_function.call(
    function_id=test_runner_id,
    input_data={
        **result2
    },
    parameters={
        "tool_model": which_model_to_use_for_tool
    }
)
print("\n=== test-runner result ===")
print(result3)


# Step4 - Remove the add functions
# Do this when  needed, If in case the functions are reasuable by other agents, then better not remove them
print("removing function")
agent_function.remove(function_id=code_validator_id, remove_deployment=True)
agent_function.remove(function_id=test_generator_id, remove_deployment=True)
agent_function.remove(function_id=test_runner_id, remove_deployment=True)
