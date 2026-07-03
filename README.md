# CosmosAI-AgentGrid

This repository contains the codebase used in our AgentGrid Agentic Platform YouTube Series. It demonstrates how to utilize the AgentGrid platform to set up agents and build dynamic applications on top of it.

## Repository Structure

The project is organized into several key directories:

### Agentic Patterns (`/agentic-patterns`)
Contains tutorials demonstrating a total of 8 distinct Agentic Patterns.

| SN No | Agentic Pattern | Video Link |
| :--- | :--- | :--- |
| 1 | Sequential Chain Pattern | [Watch Video](https://youtu.be/NkseJhF5qeg) |
| 2 | Conditional Sequence Pattern | [Watch Video](https://youtu.be/4vIK1teqvl0) |
| 3 | Parallel Pattern | [Watch Video](https://youtu.be/oNWANf3lvEc) |
| 4 | Router Pattern | [Watch Video](https://youtu.be/Paec52Y3Er8) |
| 5 | Orchestrator Pattern | [Watch Video](https://youtu.be/1IMHvskjXFg) |
| 6 | Human-In-Loop Pattern | [Watch Video](https://youtu.be/hjWVSTEEeMU) |
| 7 | Critic/Reflection Pattern | [Watch Video](https://youtu.be/_csnKrMJwWc) |
| 8 | Hierarchical Pattern | [Watch Video](https://youtu.be/EY-kn56T9wI) |

- **`/agent_codes`**: Contains the Python source code for all 8 agentic patterns. This directory also includes Dockerfiles and shell scripts required to build docker images and push them to your registry.
- **`/agent_guides`**: Contains the Jupyter notebooks used during the YouTube videos. Check out [`1_Sequential_Pattern.ipynb`](agentic-patterns/agent_guides/1_Sequential_Pattern/1_Sequential_Pattern.ipynb) as a starting point to see these libraries and patterns in action.
- **`/agents_registration`**: Contains the necessary JSON registration files and scripts to easily register, unregister, deploy, and delete the agents across all 8 examples.

### Workflow Examples (`/workflows_examples`)
Contains examples showing how multiple agents can be connected dynamically to form complex workflows using Specification files.

| SN No | Workflow Name | Folder Link | Video Link |
| :--- | :--- | :--- | :--- |
| 1 | Simple Agentic Workflow | [`/workflows_examples/simple-workflow`](workflows_examples/simple-workflow) | [Watch Video](https://youtu.be/Y5hNYNoVMDA) |
| 2 | Multi Level Agentic Workflow | [`/workflows_examples/multi-level-workflow`](workflows_examples/multi-level-workflow) | [Watch Video](https://youtu.be/ploms98oH_8) |
| 3 | Hierarchical Agentic Workflow | [`/workflows_examples/hierarchical-workflow`](workflows_examples/hierarchical-workflow) | [Watch Video](https://youtu.be/qoXMN0Ha7zI) |
| 4 | Hybrid Agentic Workflow | [`/workflows_examples/simple-workflow2`](workflows_examples/simple-workflow2) | [Watch Video](https://youtu.be/rmW30iJPDRU) |
| 5 | Behavioral Agentic Workflow | [`/workflows_examples/behavioral-workflow`](workflows_examples/behavioral-workflow) | [Watch Video](https://youtu.be/5KWnLwMO4Ec0) |

- **`/simple-workflow`**: Teaches how to build a simple sequential workflow.
- **`/multi-level-workflow`**: Demonstrates how to achieve nestedness, allowing sub-workflows to be utilized within main workflow specifications.
- **`/hierarchical-workflow`**: Demonstrates a multi-layered hierarchical workflow led by a CEO and Chief of Staff (COS) who coordinate budget estimations and task executions across multiple dedicated teams (Finance, Marketing, Architecture, Developer, Testing), each with their own team leads and specialized subordinate agents.
- **`/simple-workflow2`**: Demonstrates a hybrid workflow combining static workflow with dynamic routing and finally a static sub-workflow (e.g., Risk Identifier -> Compliance Checker -> Negotiation Advisor -> Legal Memo).
- **`/behavioral-workflow`**: Demonstrates a behavioral workflow using function calling execution, coordinating agents that run tasks against predefined multi-stage graphs which sets required behavior to the agent under consideration.

### Service-grid (Functions & Tools) Examples (`/servicegrid-examples`)
Contains examples demonstrating how to use the Service-Grid stack to run functions and tools inside the agents.

| SN No | Example Name | Folder Link | Video Link |
| :--- | :--- | :--- | :--- |
| 1 | Functions Usage Demo | [`/servicegrid-examples/functions-usage-demo`](servicegrid-examples/functions-usage-demo) | [Watch Video](https://youtu.be/2po7fevykOc) |
| 2 | Tools Usage Demo | [`/servicegrid-examples/tools-usage-demo`](servicegrid-examples/tools-usage-demo) | [Watch Video](https://youtu.be/m1v6GEmh224) |

- **`/functions-usage-demo`**: Demonstrates how agents can access and call deployed functions. Functions run completely outside of the agent's code execution context, ensuring they do not consume any CPU cycles or RAM from the agent itself.
- **`/tools-usage-demo`**: Demonstrates how agents utilize tools. Unlike functions, tools execute directly within the agent's code context, providing local execution capabilities.

> [!TIP]
> **Quick Testing without Agent Registration**
> You can quickly test functions and tools integration without writing agent code or registering agents. These test scripts allow for rapid integration testing:
> - **Functions Quick Test**: Explore [`servicegrid-examples/functions-usage-demo/functions/test.py`](servicegrid-examples/functions-usage-demo/functions/test.py) to test function execution.
> - **Tools Quick Test**: Explore [`servicegrid-examples/tools-usage-demo/tools/tools_openai_test.py`](servicegrid-examples/tools-usage-demo/tools/tools_openai_test.py) to test tool integration examples.

### Observability (Promethius and Grafana Loki with Grafana Dashboard) Examples (`/servicegrid-examples`)
Contains examples demonstrating how to use the Service-Grid stack with observability tools like Prometheus and Grafana Loki, along with pre-built Grafana Dashboards.

| SN No | Example Name | Folder Link | Video Link |
| :--- | :--- | :--- | :--- |
| 1 | Metrics Demo (Tools) | [`/servicegrid-examples/metrics-demo`](servicegrid-examples/metrics-demo) | [Watch Video](https://youtu.be/zwUfoegaMQI)|
| 2 | Metrics Demo with Functions | [`/servicegrid-examples/metrics-demo-with-functions`](servicegrid-examples/metrics-demo-with-functions) | [Watch Video](https://youtu.be/ViV44TSGSvY)|

- **[`metrics-demo`](servicegrid-examples/metrics-demo)**: Tool example code available in [`tools-usage-demo`](servicegrid-examples/tools-usage-demo) with added metrics integration code for both the agent code and the tool's Python code.
- **[`metrics-demo-with-functions`](servicegrid-examples/metrics-demo-with-functions)**: Function example code available in [`functions-usage-demo`](servicegrid-examples/functions-usage-demo) with added metrics to the agent code and the function's Python code.
- **[`metrics_util.py`](servicegrid-examples/utils/metrics_util.py)**: Helper library containing user-defined sample metrics.
- **Grafana Dashboards**: Dashboard configurations at [`servicegrid-examples/metrics-demo/grafana_dashboard.json`](servicegrid-examples/metrics-demo/grafana_dashboard.json) and [`servicegrid-examples/metrics-demo-with-functions/grafana_dashboard.json`](servicegrid-examples/metrics-demo-with-functions/grafana_dashboard.json) that can be imported to view agent and service metrics as graphs in Grafana.

### Memorygrid Usage (2 Ways of MemoryGrid access ) (`/memorygrid-examples`)
Memory-Grid provides comprehensive storage services and agentic memory capabilities, spanning low-level, high-throughput infrastructure storage to high-level cognitive memory systems.

| SN No | Example Name | Folder Link | Video Link |
| :--- | :--- | :--- | :--- |
| 1 | MemoryGrid access at Infra Level (Context KV & FrameDB) | [`example_context_kv.py`](memorygrid-examples/infra_level_access/examples/example_context_kv.py) and [`infra_level_access`](memorygrid-examples/infra_level_access/examples) | |
| 2 | MemoryGrid's Higher-Level Abstraction (agentic-memory) | [`/memorygrid-examples/examples`](memorygrid-examples/examples) | |

- **`MemoryGrid access at Infra Level`**:
  - **Context KV Memory**: A scoped, active scratchpad backed by Redis. Each entry can be stored as key-value pairs of arbitrary JSON-serialized dictionaries. It provides fast, low-latency O(1) reads and writes for ephemeral, in-flight agent state during a session without requiring a vector embedding pipeline. Code examples are available in [`example_context_kv.py`](memorygrid-examples/examples/example_context_kv.py).
  - **Via FrameDB Memory**: The persistent and shared-memory subsystem of the [AGI Grid](https://www.AGIGr.id) ecosystem. It gives AI agents and agent societies a distributed, multi-modal memory grid that can store, route, and retrieve arbitrary objects (documents, video, sensor data, model snapshots, AI inputs/outputs, etc.) across **in-memory** (queues/caching via Redis), **persistent** (TiDB or MySQL-compatible DBs with optional S3 backup), and **streaming** (Redis streams) backends through a single, unified API. Code examples are available in [`/memorygrid-examples/infra_level_access/examples`](memorygrid-examples/infra_level_access/examples).
- **`MemoryGrid's Higher-Level Abstraction (agentic-memory)`**: Offers a five-type cognitive memory abstraction library that gives AI agents a structured, queryable, and semantically-searchable memory system:
  - **Episodic Memory**: Time-bound events and session logs ("What happened?"). [`Code Example`](memorygrid-examples/examples/example_episodic.py)
  - **Semantic Memory**: Knowledge graph facts stored as subject-predicate-object triples ("What is true?"). [`Code Example`](memorygrid-examples/examples/example_semantic.py)
  - **Procedural Memory**: Reusable skills with ordered steps ("How do I do this?"). [`Code Example`](memorygrid-examples/examples/example_procedural.py)
  - **Reflective Memory**: Distilled insights and lessons from past experience ("What did I learn?"). [`Code Example`](memorygrid-examples/examples/example_reflective.py)
  - **Reward Memory**: Reinforcement-learning state-action-reward feedback ("What works best?"). [`Code Example`](memorygrid-examples/examples/example_reward.py)

## Core Libraries & Architecture

Our agent sample codes rely on two primary libraries for interfacing and integration:

- **`agents_llm`**: The core library required to interface with Large Language Models. It abstracts the LLM integration, whether the model is hosted natively in AIGrid, or provided by third-party services like Gemini, OpenAI, or others.
- **`agents_sdk`**: This library handles the integration touch points and the lifecycle of your agent code within the AgentGrid platform. Key features include:
  - **Human-in-the-Loop (HITL)** service client interfacing.
  - **Agent Search** capabilities to discover other agents dynamically.
  - **Agent Communication** protocols, supporting Direct, Peer-to-Peer, and Delegate methods.
  - **Observability Metrics**: [`metrics.py`](servicegrid-examples/agents_sdk/core/metrics.py) provides metrics primitives of Prometheus such that we can create a higher level of custom metrics as in [`metrics_util.py`](servicegrid-examples/utils/metrics_util.py).
- **`agents_search`**: A library used to search for registered agents dynamically by providing a natural language prompt.
- **`agents_functions`** (`/servicegrid-examples/agents_functions`): Provides function integration primitives, helping in accessing deployed functions via Python code without having to perform manual curl calls.
- **`agents_tools`** (`/servicegrid-examples/agents_tools`): Used for tools access. Similar to functions, this library abstracts tool usage within the agent.
- **`framedb_sdk`** ([`/memorygrid-examples/framedb_sdk`](memorygrid-examples/framedb_sdk)): This SDK is used to interact with FrameDB (supporting in-memory, storage, and stream operations with sdk level cache). **`This is the SDK preffered for interacting with FrameDB of MemoryGrid.`**
- **`framedb_writer_client`** ([`memorygrid-examples/framedb_writer_client`](memorygrid-examples/framedb_writer_client)): This SDK can be used in applications that need to write data to FrameDB(supporting in-memory, storage, and stream operations) but don't need to read from it and also dont need Cache support. Uses `object_api` Service of FrameDB.

### Execution & Registration Model
* **Execution Difference**: **Functions** run completely outside of the agent's code, meaning they do not consume any RAM or CPU clocks/cycles from the agents themselves as they run completely independent of them. In contrast, **Tools** run directly within the agent's execution code.
* **Registration & Code Upload**: The registration of agents, functions, and tools happens outside of these libraries. APIs are provided separately to register and upload the code for both functions and tools.

## Installation Requirements
### *1.Docker* 
```
sudo apt update
sudo apt install ca-certificates curl gnupg

sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker $USER


sudo nano /etc/docker/daemon.json
{
  "runtimes": {
    "runsc": {
      "path": "/usr/bin/runsc"
    }
  },
  "insecure-registries": ["REGISTRYIP:31280"]
}
sudo systemctl restart docker
```
### *2. Python Virtual Environment*
- Create a venv at root of the project i.e in `CosmosAI-AgentGrid/`. Run `python3 -m venv venv`. Then activate the virtual environment by running `source venv/bin/activate`. 
- In this venv you would be running Jupyter notebook and streamlit app.Install packages: `pip3 install notebook streamlit load_dotenv`.
- Go to `CosmosAI-AgentGrid/` and run `jupyter notebook --allow-root  --port 8002 --ip=0.0.0.0` to start the jupyter notebook. And Go to browser and open `http://IP:8002`
- To Securely Run: `jupyter notebook password` to generate one time password for secure access
- To Clear Outputs: Use `jupyter nbconvert --clear-output --inplace YOUR_JUPYTER_NOTEBOOK_NAME.ipynb` 

## Quick Start

1. Review the [`1_Sequential_Pattern.ipynb`](agentic-patterns/agent_guides/1_Sequential_Pattern/1_Sequential_Pattern.ipynb) notebook to understand the SDK and LLM integration basics.
2. Configure your `.env` file using `.env.template` with your registry and AIGrid settings. Replace all the variables with your actual values.
3. Use the respective jupter notebooks to understand different agentic patterns and how to use them to build agentic applications.





