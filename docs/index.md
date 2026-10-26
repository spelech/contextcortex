---
layout: home

hero:
  name: ContextCortex
  text: High-Performance Syntax-Aware Code RAG & MCP Server
  tagline: Tree-sitter AST Code Intelligence, Calibrated Hybrid Search, and FastMCP 2.0 Server with Interactive Codebase Navigation
  actions:
    - theme: brand
      text: Get Started
      link: /guide/getting-started
    - theme: alt
      text: User Guide
      link: /guide/user-guide
    - theme: alt
      text: Architecture
      link: /architecture/
    - theme: alt
      text: View on GitHub
      link: https://github.com/spelech/contextcortex

features:
  - title: Dual-Engine Persistence
    details: Run with PostgreSQL 16 and pgvector HNSW cosine indexing in production, or zero-dependency SQLite WAL caching for local development.
  - title: FastMCP 2.0 & 16 Agent Tools
    details: Expose 16 specialized MCP tools over SSE and Streamable HTTP transports with zero-allocation JSON-RPC ping and RFC 9728 OAuth 2.1 RBAC.
  - title: Syntax-Aware AST Chunking
    details: Parse 10 programming languages with Tree-sitter to extract functions, classes, signatures, REST API routes, and caller-callee graphs.
  - title: Calibrated Hybrid Search & Navigator
    details: Combine dense semantic vectors with BM25 lexical matching using tunable weights, and inspect files in the Hero Split Codebase Navigator.
---

## Quick Documentation Navigation

| Section | Key Topics | Entry Point |
| :--- | :--- | :--- |
| **Getting Started & Configuration** | Installation, Docker Compose stack, environment variables, database profiles, and LiteLLM proxy setup. | [Overview](/guide/) · [Getting Started](/guide/getting-started) · [Configuration](/guide/configuration) |
| **User Guide (Web Dashboard)** | Overview metrics, Codebase Navigator & Omni-Search (`Ctrl+K`), Search & Inspector, Git Repositories, Local Paths, Storage & PDF OCR, Settings, Diagnostics, and Themes. | [User Guide Hub](/guide/user-guide) · [Navigator](/guide/user-guide/navigator) · [Search Inspector](/guide/user-guide/search) |
| **System Architecture** | Component interactions, Tree-sitter AST chunking pipeline, calibrated hybrid search scoring, MCP transports, OAuth 2.1 RBAC, and unified database ERD. | [Architecture Overview](/architecture/) · [System Design](/architecture/system-design) · [Data Pipeline](/architecture/data-pipeline) |
| **Reference Manual** | Complete specification of all 16 MCP tools, dynamic resources, guided prompts, Admin REST API routes, and contributor workflows. | [MCP Tools Reference](/reference/mcp-tools) · [Admin REST API](/reference/rest-api) · [Developer Guide](/reference/developer) |
| **Software Requirements (SRS)** | Functional requirements, non-functional latency/maintainability targets, and automated verification traceability across 1,037 tests. | [SRS Overview](/requirements/) · [Functional](/requirements/functional) · [Verification Matrix](/requirements/verification) |
