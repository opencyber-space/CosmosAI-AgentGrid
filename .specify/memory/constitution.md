<!-- 
Sync Impact Report:
- Version change: 0.0.0 -> 1.0.0
- Added principles: 
  - I. Reference Implementations Repository
  - II. Kubernetes-First End-to-End Testing
  - III. Strict Environment Configuration Security
  - IV. Multi-Project Integration Focus
- Added sections:
  - Environmental & Testing Constraints
  - Coding Standards & Best Practices
- Deferred items: None
-->

# CosmosAI-AgentGrid Constitution

## Core Principles

### I. Reference Implementations Repository

This repository exists to host sample code and reference implementations for various opencyber-space projects (including AgentGrid, MemoryGrid, ServiceGrid, PolicyGrid, Openarcade, XChange, and OpenMesh). Code here should clearly demonstrate practical usage, such as agentic patterns, workflows, and bidding systems.

### II. Kubernetes-First End-to-End Testing

Due to the interconnected nature of Opencyberspace projects, local tests are restricted to isolated functional mocks. Full end-to-end testing MUST be executed within a Kubernetes cluster environment. All validation logic must assume deployment in K8s.

### III. Strict Environment Configuration Security (NON-NEGOTIABLE)

Under no circumstances should agentic coding read from, parse, or directly use the `.env` file. To understand environmental variables, network configurations, or cluster IPs, agents MUST consult `.env.template`. The `.env` file is strictly off-limits. If Any variable value needed from .env then write suitable bashsccript to get the details from `.env` file by understanding the`.env.template`structure.

### IV. Multi-Project Integration Focus

Implementations often span multiple distinct projects (e.g., combining Openarcade, XChange, and OpenMesh with AgentGrid). Code must clearly delineate responsibilities and correctly utilize the linked services according to their designated boundaries.

## Environmental & Testing Constraints

Testing and interacting with the cluster must utilize the `KUBECTL_COMMAND` alias provided by the user's environment (e.g., from `~/.bashrc` as defined in `.env.template`). Agents must ensure scripts and tests correctly leverage these commands rather than hardcoding local ports or isolated Docker networks.

## Coding Standards & Best Practices

All new agentic patterns, workflow examples, and service examples must be neatly organized into their respective directories (e.g., `agentic-patterns`, `bids_example`, `workflows_examples`). Each example must remain self-contained but correctly reference its upstream Opencyberspace dependencies.

## Governance

This constitution supersedes all other practices for CosmosAI-AgentGrid. Amendments require documentation and approval. All PRs and automated agent tools must verify compliance with the environment security rule (Principle III).

**Version**: 1.0.0 | **Ratified**: 2026-09-09 | **Last Amended**: 2026-09-09
