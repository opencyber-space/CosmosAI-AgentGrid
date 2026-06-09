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
| 5 | Behavioral Agentic Workflow | [`/workflows_examples/behavioral-workflow`](workflows_examples/behavioral-workflow) | |

- **`/simple-workflow`**: Teaches how to build a simple sequential workflow.
- **`/multi-level-workflow`**: Demonstrates how to achieve nestedness, allowing sub-workflows to be utilized within main workflow specifications.
- **`/hierarchical-workflow`**: Demonstrates a multi-layered hierarchical workflow led by a CEO and Chief of Staff (COS) who coordinate budget estimations and task executions across multiple dedicated teams (Finance, Marketing, Architecture, Developer, Testing), each with their own team leads and specialized subordinate agents.
- **`/simple-workflow2`**: Demonstrates a hybrid workflow combining static workflow with dynamic routing and finally a static sub-workflow (e.g., Risk Identifier -> Compliance Checker -> Negotiation Advisor -> Legal Memo).
- **`/behavioral-workflow`**: Demonstrates a behavioral workflow using function calling execution, coordinating agents that run tasks against predefined multi-stage graphs which sets required behavior to the agent under consideration.

## Core Libraries & Architecture

Our agent sample codes rely on two primary libraries for interfacing and integration:

- **`agents_llm`**: The core library required to interface with Large Language Models. It abstracts the LLM integration, whether the model is hosted natively in AIGrid, or provided by third-party services like Gemini, OpenAI, or others.
- **`agents_sdk`**: This library handles the integration touch points and the lifecycle of your agent code within the AgentGrid platform. Key features include:
  - **Human-in-the-Loop (HITL)** service client interfacing.
  - **Agent Search** capabilities to discover other agents dynamically.
  - **Agent Communication** protocols, supporting Direct, Peer-to-Peer, and Delegate methods.

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





