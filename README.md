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

- **`/simple-workflow`**: Teaches how to build a simple sequential workflow.
- **`/multi-level-workflow`**: Demonstrates how to achieve nestedness, allowing sub-workflows to be utilized within main workflow specifications.

## Core Libraries & Architecture

Our agent sample codes rely on two primary libraries for interfacing and integration:

- **`agents_llm`**: The core library required to interface with Large Language Models. It abstracts the LLM integration, whether the model is hosted natively in AIGrid, or provided by third-party services like Gemini, OpenAI, or others.
- **`agents_sdk`**: This library handles the integration touch points and the lifecycle of your agent code within the AgentGrid platform. Key features include:
  - **Human-in-the-Loop (HITL)** service client interfacing.
  - **Agent Search** capabilities to discover other agents dynamically.
  - **Agent Communication** protocols, supporting Direct, Peer-to-Peer, and Delegate methods.

## Quick Start

1. Clone the repository.
2. Review the [`1_Sequential_Pattern.ipynb`](agentic-patterns/agent_guides/1_Sequential_Pattern/1_Sequential_Pattern.ipynb) notebook to understand the SDK and LLM integration basics.
3. Configure your `.env` file using `.env.template` with your registry and AIGrid settings.
4. Navigate to `/agentic-patterns/agents_registration/1_serial_meeting_agend_agents` and run `all.bash` to build and push your Docker images using the provided bash scripts and to deploy the agents in AgentGrid.
5. For other patterns, use the specific scripts within `/agentic-patterns/agents_registration/` to build, register, and deploy your agents.
