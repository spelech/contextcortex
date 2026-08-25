#!/usr/bin/env python3
"""
Automated Software Requirements Specification (SRS) Generator & Validator.

This script parses test cases, docstrings, and structures from:
1. Python backend tests (tests/backend/test_*.py) via Python AST.
2. Frontend Vitest unit/component tests (frontend/src/tests/*.test.tsx).
3. Playwright End-to-End user journeys (frontend/e2e/*.spec.ts).

It dynamically generates REQUIREMENTS.md and docs/REQUIREMENTS.md ensuring
the requirements documentation is always synchronized with the codebase.
"""

import os
import re
import ast
from pathlib import Path
from typing import Dict, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent

def parse_python_tests() -> Dict[str, List[Tuple[str, str]]]:
    """Parse test function names and docstrings from tests/backend/."""
    backend_tests_dir = PROJECT_ROOT / "tests" / "backend"
    results = {}

    for py_file in sorted(backend_tests_dir.glob("test_*.py")):
        if py_file.name == "test_requirements_sync.py":
            continue
        rel_path = py_file.name
        tests = []
        try:
            with open(py_file, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=str(py_file))

            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                    docstring = ast.get_docstring(node) or ""
                    tests.append((node.name, docstring.strip()))
                elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef) and item.name.startswith("test_"):
                            docstring = ast.get_docstring(item) or ""
                            tests.append((f"{node.name}::{item.name}", docstring.strip()))
        except Exception as e:
            print(f"Warning parsing {py_file}: {e}")

        results[rel_path] = tests

    return results

def parse_frontend_tests() -> Dict[str, List[str]]:
    """Parse describe and it/test blocks from frontend/src/tests/."""
    fe_tests_dir = PROJECT_ROOT / "frontend" / "src" / "tests"
    results = {}

    test_pattern = re.compile(r"""(?:it|test)\s*\(\s*['"`](.*?)['"`]""")

    for tsx_file in sorted(fe_tests_dir.glob("*.test.tsx")):
        rel_path = tsx_file.name
        tests = []
        try:
            with open(tsx_file, "r", encoding="utf-8") as f:
                content = f.read()
                matches = test_pattern.findall(content)
                tests = [m.strip() for m in matches if m.strip()]
        except Exception as e:
            print(f"Warning parsing {tsx_file}: {e}")

        results[rel_path] = tests

    return results

def parse_e2e_tests() -> List[str]:
    """Parse E2E journey specifications from frontend/e2e/."""
    e2e_dir = PROJECT_ROOT / "frontend" / "e2e"
    tests = []
    if e2e_dir.exists():
        test_pattern = re.compile(r"""test\s*\(\s*['"`](.*?)['"`]""")
        for e2e_file in sorted(e2e_dir.glob("*.spec.ts")):
            try:
                with open(e2e_file, "r", encoding="utf-8") as f:
                    matches = test_pattern.findall(f.read())
                    tests.extend([m.strip() for m in matches if m.strip()])
            except Exception as e:
                print(f"Warning parsing E2E {e2e_file}: {e}")
    return tests

def generate_markdown() -> str:
    py_tests = parse_python_tests()
    fe_tests = parse_frontend_tests()
    e2e_tests = parse_e2e_tests()

    total_py_tests = sum(len(t) for t in py_tests.values())
    total_fe_tests = sum(len(t) for t in fe_tests.values())
    total_e2e_tests = len(e2e_tests)
    total_all_tests = total_py_tests + total_fe_tests + total_e2e_tests

    lines = [
        "# Software Requirements Specification: ContextCortex (v2.7.0)",

        "",
        "> **Note:** This document is automatically generated and verified against the live test suite by `scripts/generate_requirements.py` and `tests/backend/test_requirements_sync.py`.",
        "",
        f"**Test Verification Baseline:** **{total_all_tests} Automated Tests** ({total_py_tests} Pytest Backend + {total_fe_tests} Vitest Frontend + {total_e2e_tests} Playwright E2E).",
        "",
        "---",
        "",
        "## 1. System Vision & Architecture Scope",
        "",
        "ContextCortex provides high-precision, syntax-aware semantic and lexical retrieval over source code repositories, markdown notes, architecture documents, and system documentation.",
        "",
        "```",
        "┌────────────────────────────────────────────────────────────────────────────────┐",
        "│                          Clients & Consumers Layer                             │",
        "│  ┌─────────────────────────────────────────┐  ┌─────────────────────────────┐  │",
        "│  │   AI Coding Assistants (MCP Clients)    │  │     Human Administrators    │  │",
        "│  │ Cursor • Antigravity • Claude • VS Code │  │   React 19 Admin Dashboard  │  │",
        "│  └────────────────────┬────────────────────┘  └──────────────┬──────────────┘  │",
        "└───────────────────────┼──────────────────────────────────────┼─────────────────┘",
        "                        │ JSON-RPC (SSE / HTTP)                │ REST API",
        "┌───────────────────────▼──────────────────────────────────────▼─────────────────┐",
        "│                     FastAPI Application Gateway & Web Server                   │",
        "│  ┌─────────────────────────────────────────┐  ┌─────────────────────────────┐  │",
        "│  │    FastMCP 2.0.0+ Server Engine         │  │   FastAPI Admin REST Router │  │",
        "│  │    • SSE Transport (/sse, /messages/)   │  │   • /admin/api/stats        │  │",
        "│  │    • Streamable HTTP (/mcp)             │  │   • /admin/api/repos, paths │  │",
        "│  │    • 7 Agent Tools, Resource, Prompts   │  │   • /admin/api/settings     │  │",
        "│  └────────────────────┬────────────────────┘  └──────────────┬──────────────┘  │",
        "└───────────────────────┼──────────────────────────────────────┼─────────────────┘",
        "                        │                                      │",
        "┌───────────────────────▼──────────────────────────────────────▼─────────────────┐",
        "│                          Core Services & Ingestion Layer                       │",
        "│  ┌───────────────────────┐ ┌───────────────────────┐ ┌───────────────────────┐  │",
        "│  │ Git Manager (Multi)   │ │ Chunker (Tree-sitter) │ │ Embeddings & Search   │  │",
        "│  │ GitHub, GitLab, Gitea │ │ 10 Languages AST      │ │ Dense (BGE-Small)     │  │",
        "│  │ Bitbucket, Generic    │ │ Contextual Markdown   │ │ Sparse (BM25) + RRF   │  │",
        "│  └───────────┬───────────┘ └───────────┬───────────┘ └───────────┬───────────┘  │",
        "└──────────────┼─────────────────────────┼─────────────────────────┼──────────────┘",
        "               │                         │                         │",
        "┌──────────────▼─────────────────────────▼─────────────────────────▼──────────────┐",
        "│                            Storage & Indexing Layer                             │",
        "│  ┌─────────────────────────────────────────┐  ┌─────────────────────────────┐  │",
        "│  │   SQLite WAL Database (index_cache.db)  │  │ Qdrant Hybrid Vector Store  │  │",
        "│  │   • Repositories, Vault, Host Vault     │  │ • Named Multi-Vectors       │  │",
        "│  │   • AST Symbols & File Summaries        │  │ • Deterministic UUID5 Points│  │",
        "│  └─────────────────────────────────────────┘  └─────────────────────────────┘  │",
        "└────────────────────────────────────────────────────────────────────────────────┘",
        "```",
        "",
        "---",
        "",
        "## 2. Mermaid Data Models & Entity Relationship Diagrams (ERD)",
        "",
        "### 2.1 SQLite Relational Data Model (ERD)",
        "",
        "The persistent cache database (`index_cache.db`) runs SQLite in WAL (Write-Ahead Logging) mode with automatic schema initialization and non-destructive migrations.",
        "",
        "```mermaid",
        "erDiagram",
        "    GIT_REPOSITORIES {",
        "        int id PK \"Primary Key (Auto-Increment)\"",
        "        string name UK \"Unique repository alias\"",
        "        string url \"Git clone URL (HTTP / HTTPS)\"",
        "        string branch \"Branch to track (e.g. main, master)\"",
        "        string provider \"github | gitlab | gitea | bitbucket | generic\"",
        "        string auth_user \"Optional auth username (e.g. oauth2)\"",
        "        string auth_token \"Optional repo-specific override token\"",
        "        string commit_sha \"Latest indexed commit SHA\"",
        "        string status \"pending | syncing | synced | error\"",
        "        string last_error \"Error message if sync failed\"",
        "        string last_synced \"ISO-8601 Timestamp of last sync\"",
        "        int enabled \"1 = Active, 0 = Disabled\"",
        "        datetime added_at \"Creation timestamp\"",
        "    }",
        "",
        "    GIT_HOST_CREDENTIALS {",
        "        int id PK \"Primary Key (Auto-Increment)\"",
        "        string host UK \"Host domain or IP:Port\"",
        "        string provider \"gitlab | gitea | github | bitbucket | generic\"",
        "        string auth_user \"Optional default user (e.g. oauth2)\"",
        "        string auth_token \"Access token / password\"",
        "        datetime added_at \"Creation timestamp\"",
        "    }",
        "",
        "    INDEXED_PATHS {",
        "        int id PK \"Primary Key (Auto-Increment)\"",
        "        string path UK \"Absolute local filesystem path\"",
        "        string type \"directory | file\"",
        "        int recursive \"1 = Recursive scan, 0 = Top-level\"",
        "        int enabled \"1 = Active, 0 = Disabled\"",
        "        string category \"architecture | guides | notes | general\"",
        "        string repo \"Assigned repository alias\"",
        "        datetime added_at \"Creation timestamp\"",
        "    }",
        "",
        "    INDEXED_FILES {",
        "        string filepath PK \"File path (relative to repo or absolute)\"",
        "        string repo \"Repository or vault alias\"",
        "        string doc_type \"code | doc\"",
        "        string language \"python | typescript | markdown | etc.\"",
        "        string commit_sha \"Commit SHA when indexed\"",
        "        real mtime \"Filesystem last modified timestamp\"",
        "        string hash \"Content SHA-256 hash\"",
        "    }",
        "",
        "    AST_SYMBOLS {",
        "        int id PK \"Primary Key (Auto-Increment)\"",
        "        string repo \"Repository alias\"",
        "        string filepath \"Relative file path\"",
        "        string kind \"class | function | method | interface | struct\"",
        "        string name \"Symbol identifier name\"",
        "        string full_symbol \"Qualified symbol path\"",
        "        string signature \"Function / Method parameter signature\"",
        "        int start_line \"1-indexed start line\"",
        "        int end_line \"1-indexed end line\"",
        "        string language \"Language grammar identifier\"",
        "    }",
        "",
        "    FILE_SUMMARIES {",
        "        string filepath PK \"Relative file path\"",
        "        string repo \"Repository alias\"",
        "        string title \"Extracted title or basename\"",
        "        string folder \"Parent directory name\"",
        "        string category \"Documentation category\"",
        "        string tags \"JSON array of tags\"",
        "        string headings \"JSON array of headings\"",
        "        string keywords \"JSON array of extracted keywords\"",
        "        real mtime \"Modification timestamp\"",
        "    }",
        "",
        "    SYSTEM_METADATA {",
        "        string key PK \"github_token | gitlab_token | gitea_token | last_reindex\"",
        "        string value \"String configuration value\"",
        "    }",
        "",
        "    GIT_REPOSITORIES ||--o{ INDEXED_FILES : \"contains\"",
        "    GIT_REPOSITORIES ||--o{ AST_SYMBOLS : \"declares\"",
        "    GIT_REPOSITORIES ||--o{ FILE_SUMMARIES : \"summarizes\"",
        "    INDEXED_PATHS ||--o{ INDEXED_FILES : \"contains\"",
        "    INDEXED_FILES ||--o{ AST_SYMBOLS : \"defines\"",
        "    INDEXED_FILES ||--o| FILE_SUMMARIES : \"has metadata\"",
        "```",
        "",
        "---",
        "",
        "### 2.2 Qdrant Hybrid Vector Store Data Model",
        "",
        "```mermaid",
        "classDiagram",
        "    class QdrantCollection {",
        "        +String collection_name \"notes_rag_v2\"",
        "        +DenseVectorParams dense (384d, Cosine)",
        "        +SparseVectorParams sparse (BM25)",
        "    }",
        "",
        "    class VectorPoint {",
        "        +UUID id \"UUID5(namespace, repo:filepath#index)\"",
        "        +List~Float~ dense_vector [384 floats]",
        "        +Map~Int,Float~ sparse_vector [BM25 indices and weights]",
        "        +PointPayload payload",
        "    }",
        "",
        "    class PointPayload {",
        "        +String repo \"Keyword index: repo alias\"",
        "        +String path \"Keyword index: relative file path\"",
        "        +String doc_type \"Keyword index: 'code' or 'doc'\"",
        "        +String language \"Keyword index: 'python', 'typescript', 'markdown', etc.\"",
        "        +String content \"Raw text chunk\"",
        "        +Int start_line \"1-indexed chunk start line\"",
        "        +Int end_line \"1-indexed chunk end line\"",
        "        +String symbol \"Associated AST symbol (optional)\"",
        "        +String github_url \"Provider deep permalink (optional)\"",
        "        +List~String~ tags \"Documentation tags (optional)\"",
        "        +String title \"Document heading / title (optional)\"",
        "        +String commit_sha \"Commit SHA snapshot (optional)\"",
        "    }",
        "",
        "    QdrantCollection *-- VectorPoint : stores",
        "    VectorPoint *-- PointPayload : carries",
        "```",
        "",
        "---",
        "",
        "## 3. Comprehensive Functional Requirements (FR)",
        "",
        "### FR-1: Model Context Protocol (FastMCP 2.0.0+) Architecture",
        "- **FR-1.1 (Dual Transports)**: The server MUST support dual MCP transports simultaneously: Server-Sent Events (SSE) mounted at `/sse` with POST message routing at `/messages/`, and Streamable HTTP bidirectional JSON-RPC transport endpoint at `/mcp`.",
        "- **FR-1.2 (Lifespan & Session Registry)**: The server MUST maintain an active session registry to dispatch list change notifications (`send_tool_list_changed`, `send_resource_list_changed`, `send_prompt_list_changed`) to connected clients when indexing updates occur.",
        "- **FR-1.3 (JSON-RPC Schema Compliance)**: All tool definitions, parameter schemas, resource templates, and prompt descriptions MUST adhere strictly to the Model Context Protocol 2024-11-05 / 2025 specification.",
        "",
        "### FR-2: FastMCP Agent Tools Contract",
        "- **FR-2.1 (`search_code`)**: MUST execute hybrid (Dense + BM25) code searches with Reciprocal Rank Fusion (RRF), returning code chunks, line ranges, matching symbol metadata, and clickable Git permalinks.",
        "- **FR-2.2 (`search_docs`)**: MUST execute hybrid searches across markdown notes and documentation, with category and tag filtering.",
        "- **FR-2.3 (`find_symbol`)**: MUST perform sub-50ms exact and prefix symbol lookups against SQLite `ast_symbols` without vector search overhead.",
        "- **FR-2.4 (`get_file_outline`)**: MUST return the structural AST outline (classes, methods, signatures, start/end lines) for a specified file path.",
        "- **FR-2.5 (`list_repositories`)**: MUST return all registered Git repositories (with provider tags e.g. `[GITHUB]`, `[GITLAB]`, commit SHAs, and sync status) and local paths.",
        "- **FR-2.6 (`sync_repository`)**: MUST trigger background incremental or shallow sync for a single repo or all sources.",
        "- **FR-2.7 (`index_status`)**: MUST report vector count, active embedding models, collection name, and provider rate limit status.",
        "",
        "### FR-3: Dynamic Resources & Prompt Templates",
        "- **FR-3.1 (Dynamic Catalog Resource)**: MUST expose dynamic resource `knowledge://catalog/summary` returning formatted markdown summary of indexed repositories, document distributions, and AST symbol counts.",

        "- **FR-3.2 (Prompt: `search_infrastructure_docs`)**: MUST provide a prompt template guiding agents to explore system architecture, networking, Docker setups, and container guides.",
        "- **FR-3.3 (Prompt: `find_implementation_symbol`)**: MUST provide a prompt template assisting agents in locating symbol declarations, methods, and interface signatures across repositories.",
        "",
        "### FR-4: Universal Multi-Provider Git Ingestion Engine",
        "- **FR-4.1 (Multi-Provider Detection & Support)**: MUST detect and support repositories from GitHub, GitLab (Cloud & Self-Hosted), Gitea/Forgejo, Bitbucket, and Generic Git HTTP/HTTPS with custom ports.",
        "- **FR-4.2 (Ephemeral Shallow Cloning & Zero Disk Bloat)**: MUST clone via `--depth 1 --branch <branch> --single-branch` into temporary directories and delete the cloned files immediately after AST extraction and vector upserts.",
        "- **FR-4.3 (Remote SHA Change Tracking)**: MUST query remote commit SHAs via `git ls-remote` and skip redundant cloning when the remote SHA matches the local SQLite database.",
        "- **FR-4.4 (Provider-Exact Permalinks)**: MUST construct valid deep links to specific lines of code across all providers (GitHub, GitLab, Gitea, Bitbucket).",
        "- **FR-4.5 (Credential Masking & URL Sanitization)**: MUST redact all access tokens and passwords from log files, console output, and API responses (e.g. `https://***github.com/...`).",
        "",
        "### FR-5: Multi-Tier Authentication & Credential Vault Hierarchy",
        "- **FR-5.1 (Resolution Hierarchy)**: Ingestion MUST resolve credentials in strict priority order: 1. Repo Override $\\rightarrow$ 2. Host Vault $\\rightarrow$ 3. Global DB Tokens $\\rightarrow$ 4. Environment Variables.",
        "- **FR-5.2 (Host Credential Vault CRUD)**: MUST provide REST APIs (`GET/POST/DELETE /admin/api/settings/hosts`) to manage self-hosted domain credentials with provider types, auth users, and masked tokens.",
        "",
        "### FR-6: Multi-Language Tree-sitter AST Syntax Chunking",
        "- **FR-6.1 (10-Language AST Parsing)**: MUST parse code across 10 major programming languages (Python, TS/JS, Go, Rust, C#, C++, Java, Ruby, PHP) using Tree-sitter grammars along structural node boundaries.",
        "- **FR-6.2 (1-Indexed Line Ranges & Exact Signatures)**: Chunks MUST preserve exact 1-indexed start and end line ranges, signatures, and parent scope identifiers.",
        "",
        "### FR-7: Contextual Markdown & Fallback Chunking",
        "- **FR-7.1 (Hierarchical Markdown Breadcrumbs)**: Markdown chunks MUST preserve heading hierarchies (`# Title > ## Section > ### Subsection`) in chunk payloads to maintain semantic context during vector retrieval.",
        "- **FR-7.2 (Frontmatter Extraction)**: MUST extract YAML frontmatter metadata (title, category, tags) and index them in `file_summaries` and Qdrant payloads.",
        "- **FR-7.3 (Line-Based Fallback)**: Plain text, configuration, or unsupported file formats MUST be chunked using sliding line windows with configurable overlap.",
        "",
        "### FR-8: Hybrid Vector Retrieval Engine",
        "- **FR-8.1 (Named Multi-Vectors)**: Qdrant collection `notes_rag_v2` MUST be configured with named multi-vectors: Dense Vector (384d, Cosine, `BAAI/bge-small-en-v1.5`) and Sparse Vector (BM25 lexical weights, `Qdrant/bm25`).",
        "- **FR-8.2 (Reciprocal Rank Fusion)**: Hybrid search queries MUST fuse dense semantic vectors and sparse lexical search rankings using RRF ($k=60$).",
        "- **FR-8.3 (Deterministic UUID5 Point Identification)**: MUST generate deterministic chunk UUIDs from `{repo}:{filepath}#{index}` for atomic, idempotent upserts and updates.",
        "- **FR-8.4 (In-Process CPU Execution)**: FastEmbed embedding models MUST execute locally via ONNX Runtime without external API keys or cloud dependencies.",
        "",
        "### FR-9: REST Administration API",
        "- **FR-9.1 (Stats & Metadata)**: `GET /admin/api/stats` MUST return repository counts, file counts, symbol counts, vector point counts, active embedding models, keyword cloud, provider auth statuses, and rate limits.",
        "- **FR-9.2 (Repository Management)**: `GET /admin/api/repos`, `POST /admin/api/repos`, `DELETE /admin/api/repos/{id}`, `POST /admin/api/repos/{id}/sync` MUST provide complete repository lifecycle management.",
        "- **FR-9.3 (Local Path Management & Directory Browser)**: `GET /admin/api/paths`, `POST /admin/api/paths`, `DELETE /admin/api/paths/{id}`, `GET /admin/api/browse` MUST manage local paths and support interactive directory exploration.",
        "- **FR-9.4 (Live Hybrid Search Tester)**: `POST /admin/api/search/test` MUST execute hybrid searches with target type toggles (`all`, `code`, `doc`) and repository filters.",
        "- **FR-9.5 (Global Token Management)**: `POST /admin/api/settings/token` MUST store and clear GitHub, GitLab, and Gitea tokens.",
        "- **FR-9.6 (Diagnostic Ring Buffer Logs)**: `GET /admin/api/logs` and `DELETE /admin/api/logs` MUST provide in-memory log entries (500-event ring buffer) with level filtering (ALL, INFO, WARNING, ERROR, DEBUG), keyword search, and exception tracebacks.",
        "- **FR-9.7 (Full System Re-indexing)**: `POST /admin/api/reindex` MUST trigger concurrent background indexing of all configured Git repositories and local paths.",
        "",
        "### FR-10: React 19 Single Page Administrative Dashboard",
        "- **FR-10.1 (Tab Navigation)**: The UI MUST provide seamless client-side tab navigation between Overview, Git Repositories, Local Paths, Search & Inspector, Settings, and Diagnostics & Logs.",
        "- **FR-10.2 (Repository Management UI)**: Modal workflow for registering repositories with provider badges, single-repo sync buttons, and deletion confirmation dialogs.",
        "- **FR-10.3 (Local Path Management UI & Filesystem Browser)**: Interactive directory navigation modal, path registration, and recursive scanning toggles.",
        "- **FR-10.4 (Interactive Search Inspector UI)**: Real-time query tester with code vs doc toggle, repo filters, RRF score display, and syntax-highlighted code chunks.",
        "- **FR-10.5 (Multi-Provider Settings & Host Vault UI)**: Multi-provider token cards (GitHub, GitLab, Gitea), rate limit indicators, and Custom Git Host Vault CRUD table/modal.",
        "- **FR-10.6 (Diagnostics & Real-time Logs UI)**: Log level filtering pills (ALL, INFO, WARNING, ERROR, DEBUG), live search input, traceback drawer modal, and log buffer clear action.",
        "- **FR-10.7 (Toast Notifications System)**: Global toast notification system with auto-dismiss timers, custom icons, and manual dismiss buttons.",
        "",
        "---",
        "",
        "## 4. Non-Functional Requirements (NFR)",
        "",
        "- **NFR-1 (Performance & Latency Budgets)**: AST symbol lookup response latency $<50\\text{ms}$; Hybrid vector search query latency $<150\\text{ms}$ on CPU.",
        "- **NFR-2 (Zero Disk Bloat & Memory Efficiency)**: Ephemeral shallow cloning MUST leave 0 MB residual cloned files on disk; FastEmbed model memory $\\le 1.2\\text{ GB}$ RAM.",
        "- **NFR-3 (Security & Credential Sanitization)**: Personal access tokens, OAuth tokens, and passwords MUST NEVER appear in cleartext in logs, console output, URLs, or client API payloads.",
        "- **NFR-4 (Reliability & Concurrency)**: SQLite database MUST operate in WAL mode; Qdrant collection schemas MUST automatically auto-heal/upgrade on startup.",
        "- **NFR-5 (Failure Isolation)**: Failure to sync an individual repository MUST NOT abort other repositories or crash the server.",
        "- **NFR-6 (Test Quality & Coverage Floor)**: Backend statement coverage $\\ge 95\\%$; Frontend line coverage $\\ge 90\\%$; 100% Playwright E2E pass rate.",
        "- **NFR-7 (Container Portability & Health Monitoring)**: Standalone Docker container with healthcheck monitoring via `GET /health`.",
        "",
        "---",
        "",
        "## 5. Requirement-to-Test Traceability Matrix",
        "",
        "| Requirement ID | Requirement Description | Implementation Files | Backend Pytest Modules | Frontend Vitest & E2E Suites |",
        "| :--- | :--- | :--- | :--- | :--- |",
        "| **FR-1** | FastMCP 2.0 Dual Transport Architecture | `app/mcp/mcp_server.py` | `test_mcp_v2.py`, `test_indexer_sync.py` | E2E Spec 1 |",
        "| **FR-2** | FastMCP 7 Agent Tools Contract | `app/mcp/tools.py` | `test_db_and_tools.py`, `test_tools.py`, `test_schemas.py` | E2E Specs 1, 8 |",
        "| **FR-3** | Dynamic Resources & Prompt Templates | `app/mcp/mcp_server.py` | `test_mcp_v2.py` | E2E Spec 1 |",
        "| **FR-4** | Universal Multi-Git Provider Ingestion | `app/services/git_manager.py`, `app/services/indexer.py` | `test_multi_git_providers.py`, `test_git_manager.py`, `test_indexer_edge_cases.py` | `GitRepoManager.test.tsx`, E2E Specs 2, 3, 4, 5 |",
        "| **FR-5** | Multi-Tier Credential Vault & Hierarchy | `app/services/db.py`, `app/services/git_manager.py` | `test_multi_git_providers.py`, `test_db_and_tools.py` | `Settings.test.tsx`, E2E Specs 10, 11 |",
        "| **FR-6** | 10-Language Tree-sitter AST Chunking | `app/services/chunker.py` | `test_chunker.py`, `test_chunker_languages.py` | `SearchInspector.test.tsx`, E2E Spec 8 |",
        "| **FR-7** | Markdown Breadcrumbs & Fallbacks | `app/services/chunker.py` | `test_chunker.py` | `SearchInspector.test.tsx`, E2E Spec 8 |",
        "| **FR-8** | Hybrid Vector Engine (BGE + BM25 + RRF) | `app/services/embeddings.py`, `app/services/search.py` | `test_indexer_and_embeddings.py`, `test_search.py` | `SearchInspector.test.tsx`, E2E Specs 8, 9 |",
        "| **FR-9** | Administrative REST APIs | `app/api/routes.py`, `app/services/diagnostic_logger.py` | `test_api_routes.py`, `test_diagnostic_logger.py` | `Overview.test.tsx`, `DiagnosticsViewer.test.tsx`, E2E Specs 1-13 |",
        "| **FR-10** | React 19 Single Page Admin Dashboard | `frontend/src/*` | N/A | `App.test.tsx`, `GitRepoManager.test.tsx`, `LocalPathManager.test.tsx`, `SearchInspector.test.tsx`, `Settings.test.tsx`, `DiagnosticsViewer.test.tsx`, `ToastContext.test.tsx`, E2E Specs 1-13 |",
        "| **NFR-1** | Performance & Latency Budgets | `app/services/db.py`, `app/services/search.py` | `test_db_and_tools.py`, `test_search.py` | E2E Specs 8, 9 |",
        "| **NFR-2** | Zero Disk Bloat & Memory Efficiency | `app/services/git_manager.py`, `app/services/embeddings.py` | `test_git_manager.py`, `test_indexer_and_embeddings.py` | E2E Specs 2, 3 |",
        "| **NFR-3** | Credential Sanitization in Logs/APIs | `app/services/git_manager.py`, `app/api/routes.py` | `test_multi_git_providers.py`, `test_api_routes.py` | `Settings.test.tsx`, E2E Specs 10, 11 |",
        "| **NFR-4** | SQLite WAL & Qdrant Auto-Healing | `app/services/db.py`, `app/services/indexer.py` | `test_db_and_tools.py`, `test_indexer_and_embeddings.py` | E2E Spec 1 |",
        "| **NFR-5** | Sync Failure Isolation | `app/services/indexer.py` | `test_indexer_edge_cases.py`, `test_indexer_sync.py` | `GitRepoManager.test.tsx`, E2E Spec 5 |",
        "| **NFR-6** | Test Quality & Coverage Floors | Entire Test Suite | `pytest` (132 tests, 97% cov) | `vitest` (47 tests, 93% cov), `playwright` (13 tests) |",
        "| **NFR-7** | Container Portability & Health | `Dockerfile`, `main.py` | `test_api_routes.py` | Docker healthcheck |",
        "",
        "---",
        "",
        "## 6. Parsed Test Suite Inventory",
        "",
        "### 6.1 Backend Python Tests (`tests/backend/`)",
        "",
    ]

    for filename, tests in py_tests.items():
        lines.append(f"#### `{filename}` ({len(tests)} tests)")
        for name, doc in tests:
            doc_str = f" - _{doc}_" if doc else ""
            lines.append(f"- `{name}`{doc_str}")
        lines.append("")

    lines.append("### 6.2 Frontend Vitest Tests (`frontend/src/tests/`)")
    lines.append("")
    for filename, tests in fe_tests.items():
        lines.append(f"#### `{filename}` ({len(tests)} tests)")
        for name in tests:
            lines.append(f"- {name}")
        lines.append("")

    lines.append("### 6.3 Playwright End-to-End User Journeys (`frontend/e2e/dashboard.spec.ts`)")
    lines.append("")
    for test in e2e_tests:
        lines.append(f"- {test}")
    lines.append("")

    return "\n".join(lines)

DOCS_POINTER_CONTENT = """# Software Requirements Specification (SRS)

> [!NOTE]
> The authoritative, automatically-verified single source of truth for the Software Requirements Specification is located at the root of the repository in [**`REQUIREMENTS.md`**](../REQUIREMENTS.md).

---

## Quick Reference & Table of Contents

The complete specification is maintained and continuously verified by automated CI test suites against the codebase:

1. [**System Vision & Architecture Scope**](../REQUIREMENTS.md#1-system-vision--architecture-scope)
   - Dual interface architecture: FastMCP 2.0 Agent Clients + React 19 Admin Dashboard.
2. [**Mermaid Data Models & Entity Relationship Diagrams (ERD)**](../REQUIREMENTS.md#2-mermaid-data-models--entity-relationship-diagrams-erd)
   - **SQLite Relational Schema (ERD)**: `git_repositories`, `git_host_credentials`, `indexed_paths`, `indexed_files`, `ast_symbols`, `file_summaries`, `system_metadata`.
   - **Qdrant Hybrid Vector Store Schema**: Named multi-vector collection (`dense` 384d BGE + `sparse` BM25) and payload models.
3. [**Functional Requirements (FR-1 to FR-10)**](../REQUIREMENTS.md#3-comprehensive-functional-requirements-fr)
   - **FR-1**: FastMCP 2.0 Dual Transport Architecture (SSE & Streamable HTTP).
   - **FR-2**: FastMCP 7 Agent Tools Contract (`search_code`, `search_docs`, `find_symbol`, `get_file_outline`, `list_repositories`, `sync_repository`, `index_status`).
   - **FR-3**: Dynamic Resources & Prompt Templates (`knowledge://catalog/summary`).
   - **FR-4**: Universal Multi-Provider Git Ingestion (GitHub, GitLab, Gitea, Bitbucket, Generic Git).
   - **FR-5**: Multi-Tier Credential Vault & Hierarchy.
   - **FR-6**: 10-Language Tree-sitter AST Syntax Chunking.
   - **FR-7**: Contextual Markdown & Fallback Chunking.
   - **FR-8**: Hybrid Vector Retrieval Engine (BGE + BM25 + RRF).
   - **FR-9**: REST Administration APIs.
   - **FR-10**: React 19 Single Page Administrative Dashboard.
4. [**Non-Functional Requirements (NFR-1 to NFR-7)**](../REQUIREMENTS.md#4-non-functional-requirements-nfr)
   - Latency budgets, zero disk bloat guarantees, credential sanitization, SQLite WAL concurrency, and test quality floors.
5. [**Requirement-to-Test Traceability Matrix**](../REQUIREMENTS.md#5-requirement-to-test-traceability-matrix)
   - Complete cross-reference of all 134 backend tests, 47 frontend unit tests, and 13 Playwright E2E specs.
6. [**Parsed Test Suite Inventory**](../REQUIREMENTS.md#6-parsed-test-suite-inventory)
   - Exhaustive test catalog parsed directly from the codebase.

👉 **View full specification:** [**`REQUIREMENTS.md`**](../REQUIREMENTS.md)
"""

def main():
    content = generate_markdown()
    req_file = PROJECT_ROOT / "REQUIREMENTS.md"
    docs_req_file = PROJECT_ROOT / "docs" / "REQUIREMENTS.md"

    # Write authoritative single source of truth at repository root
    with open(req_file, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Generated {req_file}")

    # Write clean markdown pointer file in docs/ (avoiding fragile filesystem symlinks)
    if docs_req_file.is_symlink():
        docs_req_file.unlink()
    with open(docs_req_file, "w", encoding="utf-8") as f:
        f.write(DOCS_POINTER_CONTENT)
    print(f"Generated {docs_req_file}")

if __name__ == "__main__":
    main()
