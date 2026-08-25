# Software Requirements Specification (SRS)

> [!NOTE]
> The authoritative, automatically-verified single source of truth for the Software Requirements Specification is located at the root of the repository in [**`REQUIREMENTS.md`**](../REQUIREMENTS.md).

---

## Quick Reference & Table of Contents

The complete specification is maintained and continuously verified by automated CI test suites against the codebase:

1. [**System Vision & Architecture Scope**](../REQUIREMENTS.md#1-system-vision--architecture-scope)
   - Dual interface architecture: FastMCP 2.0 Agent Clients + React 19 Admin Dashboard.
2. [**Mermaid Data Models & Entity Relationship Diagrams (ERD)**](../REQUIREMENTS.md#2-mermaid-data-models--entity-relationship-diagrams-erd)
   - **SQLite Relational Schema (ERD)**: `git_repositories`, `git_host_credentials`, `indexed_paths`, `indexed_files`, `ast_symbols`, `ast_relationships`, `api_routes`, `api_client_calls`, `architecture_adrs`, `file_summaries`, `system_metadata`.
   - **Pluggable Vector Store Schema**: Named multi-vector collection (`dense` 384d BGE + `sparse` BM25) and payload models for Qdrant and ChromaDB.
3. [**Functional Requirements (FR-1 to FR-15)**](../REQUIREMENTS.md#3-comprehensive-functional-requirements-fr)
   - **FR-1**: FastMCP 2.0 Dual Transport Architecture (SSE & Streamable HTTP).
   - **FR-2**: FastMCP 11 Agent Tools Contract (`search_code`, `search_docs`, `find_symbol`, `get_file_outline`, `list_repositories`, `sync_repository`, `index_status`, `get_architecture`, `manage_adr`, `get_code_routes`, `trace_call_path`).
   - **FR-3**: Dynamic Resources & Prompt Templates (`knowledge://catalog/summary`).
   - **FR-4**: Universal Multi-Provider Git Ingestion (GitHub, GitLab, Gitea, Bitbucket, Generic Git).
   - **FR-5**: Multi-Tier Credential Vault & Hierarchy.
   - **FR-6**: 10-Language Tree-sitter AST Syntax & Routes.
   - **FR-7**: Contextual Markdown & Fallback Chunking.
   - **FR-8**: Pluggable Multi-Backend Vector Retrieval (Qdrant & ChromaDB).
   - **FR-9**: Codebase & Dependency Topology Graph Engine.
   - **FR-10**: Architecture Decision Records (ADR) & System Synthesis.
   - **FR-11**: Auto-Sync Poller Daemon & Webhooks.
   - **FR-12**: Administrative REST APIs & Subrouter Hierarchy.
   - **FR-13**: React 19 Single Page Administrative Dashboard.
   - **FR-14**: Interactive Visual Topology Explorer UI.
   - **FR-15**: Diagnostics & Live In-Memory Log Buffers.
4. [**Non-Functional Requirements (NFR-1 to NFR-7)**](../REQUIREMENTS.md#4-non-functional-requirements-nfr)
   - Latency budgets, zero disk bloat guarantees, credential sanitization, SQLite WAL concurrency, sub-500 LOC modularity, and test quality floors.
5. [**Requirement-to-Test Traceability Matrix**](../REQUIREMENTS.md#5-requirement-to-test-traceability-matrix)
   - Complete cross-reference across all backend tests, frontend unit tests, and Playwright E2E specs.
6. [**Parsed Test Suite Inventory**](../REQUIREMENTS.md#6-parsed-test-suite-inventory)
   - Exhaustive test catalog parsed directly from the codebase.
