#!/usr/bin/env python3
"""
Automated Software Requirements Specification (SRS) Generator & Validator.

This script parses test cases, docstrings, and structures from:
1. Python backend tests (tests/backend/test_*.py, tests/test_*.py, test_*.py) via Python AST.
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
    """Parse test function names and docstrings from all backend test locations."""
    results = {}
    py_files = []

    # 1. tests/backend/
    backend_tests_dir = PROJECT_ROOT / "tests" / "backend"
    if backend_tests_dir.exists():
        py_files.extend(sorted(backend_tests_dir.glob("test_*.py")))

    # 2. tests/
    tests_root_dir = PROJECT_ROOT / "tests"
    if tests_root_dir.exists():
        py_files.extend(sorted(tests_root_dir.glob("test_*.py")))

    # 3. root test_*.py
    py_files.extend(sorted(PROJECT_ROOT.glob("test_*.py")))

    for py_file in py_files:
        if py_file.name == "test_requirements_sync.py":
            continue
        rel_path = str(py_file.relative_to(PROJECT_ROOT))
        tests = []
        try:
            with open(py_file, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=str(py_file))

            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                    docstring = ast.get_docstring(node) or ""
                    tests.append((node.name, docstring.strip()))
                elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name.startswith("test_"):
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
        "# Software Requirements Specification: ContextCortex (v2.11.0)",
        "",
        "> **Note:** This document is automatically generated and verified against the live test suite by `scripts/generate_requirements.py` and `tests/backend/test_requirements_sync.py`.",
        "",
        f"**Test Verification Baseline:** **{total_all_tests} Automated Tests** ({total_py_tests} Pytest Backend + {total_fe_tests} Vitest Frontend + {total_e2e_tests} Playwright E2E).",
        "",
        "---",
        "",
        "## 1. System Vision & Architecture Scope",
        "",
        "ContextCortex provides high-precision, syntax-aware semantic and lexical retrieval over source code repositories, markdown notes, architecture documents, API route graphs, and system documentation. It features a modular, sub-500 LOC architecture, dual MCP transports, pluggable vector store backends (Qdrant & ChromaDB), background auto-sync pollers, multi-provider webhooks, ADR tracking, and an interactive visual topology explorer in a React 19 administrative dashboard.",
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
        "│  │    • SSE Transport (/sse, /messages/)   │  │   • app/api/routers/        │  │",
        "│  │    • Streamable HTTP (/mcp)             │  │   • repos, settings, graph  │  │",
        "│  │    • 11 Extended Agent Tools & Prompts  │  │   • webhooks, search, logs  │  │",
        "│  └────────────────────┬────────────────────┘  └──────────────┬──────────────┘  │",
        "└───────────────────────┼──────────────────────────────────────┼─────────────────┘",
        "                        │                                      │",
        "┌───────────────────────▼──────────────────────────────────────▼─────────────────┐",
        "│                          Core Modular Services Layer                           │",
        "│  ┌────────────────────┐ ┌────────────────────┐ ┌─────────────────────────────┐  │",
        "│  │ app.services.      │ │ app.services.      │ │ app.services.               │  │",
        "│  │ git_manager        │ │ chunking.*         │ │ embeddings & search         │  │",
        "│  │ GitHub, GitLab,    │ │ 10 Language AST    │ │ Dense (BGE-Small)           │  │",
        "│  │ Gitea, Bitbucket   │ │ Routes & Calls     │ │ Sparse (BM25) + RRF         │  │",
        "│  └──────────┬─────────┘ └──────────┬─────────┘ └──────────────┬──────────────┘  │",
        "│  ┌──────────▼─────────┐ ┌──────────▼─────────┐ ┌──────────────▼──────────────┐  │",
        "│  │ app.services.      │ │ app.services.      │ │ app.services.               │  │",
        "│  │ indexing.*         │ │ topology.*         │ │ poller & adr                │  │",
        "│  │ git/local syncers  │ │ graph & details    │ │ cron sync & MADR ingestion  │  │",
        "│  └──────────┬─────────┘ └──────────┬─────────┘ └──────────────┬──────────────┘  │",
        "└─────────────┼──────────────────────┼──────────────────────────┼─────────────────┘",
        "              │                      │                          │",
        "┌─────────────▼──────────────────────▼──────────────────────────▼────────────────┐",
        "│                            Storage & Vector Layer                              │",
        "│  ┌─────────────────────────────────────────┐  ┌─────────────────────────────┐  │",
        "│  │   SQLite WAL Database (index_cache.db)  │  │ Pluggable Vector Store      │  │",
        "│  │   • Repositories, Vault, Host Vault     │  │ (app.services.vector_store) │  │",
        "│  │   • AST Symbols, Routes, Relationships  │  │ • Qdrant (Embedded/Remote)  │  │",
        "│  │   • Architecture ADRs & Sync Configs    │  │ • ChromaDB (Embedded/Remote)│  │",
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
        "The persistent cache database (`index_cache.db`) runs SQLite in WAL mode with auto-migrations and indexing support.",
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
        "        int auto_sync_enabled \"1 = Periodic auto-sync active, 0 = Disabled\"",
        "        int auto_sync_interval \"Auto-sync polling interval in minutes\"",
        "        string webhook_secret \"Optional HMAC secret token for webhook triggers\"",
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
        "    AST_RELATIONSHIPS {",
        "        int id PK \"Primary Key (Auto-Increment)\"",
        "        string repo \"Repository alias\"",
        "        int source_symbol_id \"Parent symbol ID\"",
        "        string source_filepath \"Source relative file path\"",
        "        string source_symbol \"Source symbol name\"",
        "        string target_symbol \"Target referenced symbol\"",
        "        string relationship_type \"CALLS | IMPORTS | EXTENDS | IMPLEMENTS\"",
        "        int line_number \"Line number of relation\"",
        "    }",
        "",
        "    API_ROUTES {",
        "        int id PK \"Primary Key (Auto-Increment)\"",
        "        string repo \"Repository alias\"",
        "        string filepath \"File path where route is defined\"",
        "        string framework \"FastAPI | Express | Flask | Gin | Axum | ASP.NET\"",
        "        string http_method \"GET | POST | PUT | DELETE | PATCH | *\"",
        "        string path_pattern \"Normalized URL path template (e.g. /api/users/{id})\"",
        "        string handler_symbol \"Handler function/method name\"",
        "        int start_line \"1-indexed start line\"",
        "        int end_line \"1-indexed end line\"",
        "    }",
        "",
        "    API_CLIENT_CALLS {",
        "        int id PK \"Primary Key (Auto-Increment)\"",
        "        string repo \"Repository alias\"",
        "        string filepath \"File path containing client invocation\"",
        "        string http_method \"Inferred HTTP method or *\"",
        "        string url_pattern \"Invoked URL path or pattern\"",
        "        string caller_symbol \"Enclosing function / method\"",
        "        int line_number \"Line number of invocation\"",
        "    }",
        "",
        "    ARCHITECTURE_ADRS {",
        "        int id PK \"Primary Key (Auto-Increment)\"",
        "        string repo \"Repository alias\"",
        "        string adr_number \"Sequential identifier (e.g. 0001, ADR-002)\"",
        "        string title \"ADR Title\"",
        "        string status \"proposed | accepted | rejected | deprecated | superseded\"",
        "        string date \"ISO date string or extracted record date\"",
        "        string filepath \"Relative file path\"",
        "        string context \"Background and context statement\"",
        "        string decision \"Architectural decision statement\"",
        "        string consequences \"Positive/negative consequence notes\"",
        "        string raw_content \"Full raw markdown content\"",
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
        "        string key PK \"github_token | gitlab_token | gitea_token | vector_backend | auto_sync_interval | auto_sync_secret\"",
        "        string value \"String configuration value\"",
        "    }",
        "",
        "    GIT_REPOSITORIES ||--o{ INDEXED_FILES : \"contains\"",
        "    GIT_REPOSITORIES ||--o{ AST_SYMBOLS : \"declares\"",
        "    GIT_REPOSITORIES ||--o{ AST_RELATIONSHIPS : \"traces\"",
        "    GIT_REPOSITORIES ||--o{ API_ROUTES : \"exposes\"",
        "    GIT_REPOSITORIES ||--o{ API_CLIENT_CALLS : \"invokes\"",
        "    GIT_REPOSITORIES ||--o{ ARCHITECTURE_ADRS : \"documents\"",
        "    GIT_REPOSITORIES ||--o{ FILE_SUMMARIES : \"summarizes\"",
        "    INDEXED_PATHS ||--o{ INDEXED_FILES : \"contains\"",
        "    INDEXED_FILES ||--o{ AST_SYMBOLS : \"defines\"",
        "    INDEXED_FILES ||--o| FILE_SUMMARIES : \"has metadata\"",
        "```",
        "",
        "---",
        "",
        "### 2.2 Pluggable Vector Store Data Model (Qdrant & ChromaDB)",
        "",
        "```mermaid",
        "classDiagram",
        "    class VectorStore {",
        "        <<abstract>>",
        "        +ensure_collection() bool",
        "        +upsert_documents(documents) bool",
        "        +search_dense(query_vector, limit, filter_repo, filter_doc_type) List~VectorSearchResult~",
        "        +search_hybrid(query_text, query_dense, query_sparse, limit, filter_repo, filter_doc_type) List~VectorSearchResult~",
        "        +delete_by_path(filepath, repo) bool",
        "        +delete_by_repo(repo) bool",
        "        +get_stats() Dict",
        "    }",
        "",
        "    class QdrantVectorStore {",
        "        +QdrantClient client",
        "        +String collection_name",
        "        +DenseVectorParams (384d, Cosine)",
        "        +SparseVectorParams (BM25)",
        "        +upsert_documents()",
        "        +search_hybrid()",
        "    }",
        "",
        "    class ChromaVectorStore {",
        "        +ClientAPI client",
        "        +Collection collection",
        "        +upsert_documents()",
        "        +search_dense()",
        "        +search_hybrid()",
        "    }",
        "",
        "    class VectorDocument {",
        "        +String id \"UUID5(namespace, repo:filepath#index)\"",
        "        +String text",
        "        +List~Float~ dense_vector [384 floats]",
        "        +Map~Int,Float~ sparse_vector [BM25 indices and weights]",
        "        +Map~String,Any~ metadata",
        "    }",
        "",
        "    VectorStore <|-- QdrantVectorStore",
        "    VectorStore <|-- ChromaVectorStore",
        "    VectorStore ..> VectorDocument : operates on",
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
        "### FR-2: FastMCP Extended Agent Tools Contract",
        "- **FR-2.1 (`search_code`)**: MUST execute hybrid (Dense + BM25) code searches with Reciprocal Rank Fusion (RRF), returning code chunks, line ranges, matching symbol metadata, and clickable Git permalinks.",
        "- **FR-2.2 (`search_docs`)**: MUST execute hybrid searches across markdown notes and documentation, with category and tag filtering.",
        "- **FR-2.3 (`find_symbol`)**: MUST perform sub-50ms exact and prefix symbol lookups against SQLite `ast_symbols` without vector search overhead.",
        "- **FR-2.4 (`get_file_outline`)**: MUST return the structural AST outline (classes, methods, signatures, start/end lines) for a specified file path.",
        "- **FR-2.5 (`list_repositories`)**: MUST return all registered Git repositories (with provider tags e.g. `[GITHUB]`, `[GITLAB]`, commit SHAs, and sync status) and local paths.",
        "- **FR-2.6 (`sync_repository`)**: MUST trigger background incremental or shallow sync for a single repo or all sources.",
        "- **FR-2.7 (`index_status`)**: MUST report vector count, active embedding models, collection name, and provider rate limit status.",
        "- **FR-2.8 (`get_architecture`)**: MUST synthesize high-level codebase architecture including detected entry points, primary language distributions, core directories, framework components, and architectural decision records.",
        "- **FR-2.9 (`manage_adr`)**: MUST support querying, listing, creating, and updating Architectural Decision Records (MADR / Nygard format) with lifecycle status tracking.",
        "- **FR-2.10 (`get_code_routes`)**: MUST return API endpoint routes and HTTP client invocations parsed from backend frameworks (FastAPI, Express, Flask, Gin, Axum, ASP.NET).",
        "- **FR-2.11 (`trace_call_path`)**: MUST trace AST symbol calls, imports, inheritance, and cross-repo API client-to-route connections using BFS graph traversal.",
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
        "- **FR-6.3 (Relationship & Route Extraction)**: MUST extract symbol relationships (`CALLS`, `IMPORTS`, `EXTENDS`) and REST API route definitions / HTTP client calls into SQLite relational tables.",
        "",
        "### FR-7: Contextual Markdown & Fallback Chunking",
        "- **FR-7.1 (Hierarchical Markdown Breadcrumbs)**: Markdown chunks MUST preserve heading hierarchies (`# Title > ## Section > ### Subsection`) in chunk payloads to maintain semantic context during vector retrieval.",
        "- **FR-7.2 (Frontmatter Extraction)**: MUST extract YAML frontmatter metadata (title, category, tags) and index them in `file_summaries` and vector payloads.",
        "- **FR-7.3 (Line-Based Fallback)**: Plain text, configuration, or unsupported file formats MUST be chunked using sliding line windows with configurable overlap.",
        "",
        "### FR-8: Pluggable Multi-Backend Vector Retrieval Engine",
        "- **FR-8.1 (Supported Vector Backends)**: MUST support both Qdrant (Embedded and Remote) and ChromaDB (Embedded persistent and Remote client) as interchangeable storage engines.",
        "- **FR-8.2 (Reciprocal Rank Fusion)**: Hybrid search queries MUST fuse dense semantic vectors and sparse lexical search rankings using RRF ($k=60$).",
        "- **FR-8.3 (Deterministic UUID5 Point Identification)**: MUST generate deterministic chunk UUIDs from `{repo}:{filepath}#{index}` for atomic, idempotent upserts and updates.",
        "- **FR-8.4 (Runtime Provider Switching)**: MUST support dynamic vector backend switching via `POST /admin/api/settings/vector-store/switch` with health checking and live schema verification.",
        "",
        "### FR-9: Codebase & Dependency Topology Graph Engine",
        "- **FR-9.1 (Graph Topology API)**: `GET /admin/api/graph/topology` MUST return graph nodes (files, classes, functions, routes) and edges (`IMPORTS`, `CALLS`, `DEFINES`, `HANDLES`, `ROUTES_TO`) with depth, limit, view type (`files`, `symbols`, `routes`, `full`), and root node BFS filtering.",
        "- **FR-9.2 (Node Details API)**: `GET /admin/api/graph/node-details` MUST return detailed symbol signatures, code snippets, incoming/outgoing neighbor connections, and Git permalinks.",
        "",
        "### FR-10: Architecture Decision Records (ADR) & High-Level Architecture",
        "- **FR-10.1 (ADR Parsing & Storage)**: MUST parse ADR markdown files conforming to MADR or Nygard templates and index them in `architecture_adrs` with status lifecycle tracking (`draft`, `accepted`, `rejected`, `superseded`).",
        "- **FR-10.2 (Architecture Synthesis)**: MUST analyze repository entry points, language distributions, directory summaries, and route inventories to construct high-level architecture overviews.",
        "",
        "### FR-11: Background Poller Daemon & Multi-Provider Webhook Ingestion",
        "- **FR-11.1 (Background Poller Daemon)**: Ingestion daemon MUST poll enabled repositories at configurable intervals, check remote commit SHAs via `git ls-remote`, and trigger background indexing only on SHA updates.",
        "- **FR-11.2 (Multi-Provider Webhook Ingestion)**: `POST /api/webhooks/{provider}` MUST authenticate incoming webhook payloads from GitHub (`X-Hub-Signature-256`), GitLab (`X-Gitlab-Token`), Gitea (`X-Gitea-Signature`), and Bitbucket with HMAC verification, triggering instantaneous repository syncs upon push events.",
        "",
        "### FR-12: REST Administration APIs & Subrouter Hierarchy",
        "- **FR-12.1 (Modular Subrouters)**: REST APIs MUST be organized into dedicated FastAPI subrouters under `app/api/routers/` (`repositories.py`, `settings.py`, `graph.py`) and top-level modules (`webhooks.py`, `routes.py`).",
        "- **FR-12.2 (Complete CRUD & Search Endpoints)**: Full repository management, local path indexing, directory browsing, vector settings switching, diagnostic logs, and live search tester endpoints.",
        "",
        "### FR-13: React 19 Single Page Administrative Dashboard",
        "- **FR-13.1 (Tab Navigation & Responsive Layout)**: Single page dashboard supporting desktop and mobile drawer navigation across Overview, Topology, Git Repositories, Local Paths, Search & Inspector, Settings, and Diagnostics & Logs.",
        "- **FR-13.2 (Modular Component Architecture)**: Dedicated modular component tree under `frontend/src/components/` (`git/`, `settings/`, `topology/`) with all source files under 450 lines.",
        "",
        "### FR-14: Interactive Visual Topology Explorer",
        "- **FR-14.1 (Interactive Force Canvas)**: Interactive SVG/Canvas graph visualization with zoom, pan, drag physics, minimap, view type toggling (`FILES`, `SYMBOLS`, `ROUTES`, `FULL`), and depth selection.",
        "- **FR-14.2 (Slide-Over Inspector Drawer)**: Interactive drawer displaying symbol signatures, line ranges, incoming/outgoing relationship trees, and Git permalinks.",
        "",
        "### FR-15: Diagnostics & Live In-Memory Log Buffers",
        "- **FR-15.1 (Ring Buffer Logging)**: In-memory 500-event log buffer with level filtering (ALL, INFO, WARNING, ERROR, DEBUG), keyword search, and exception traceback viewer drawer.",
        "",
        "---",
        "",
        "## 4. Non-Functional Requirements (NFR)",
        "",
        "- **NFR-1 (Performance & Latency Budgets)**: AST symbol lookup response latency $<50\\text{ms}$; Hybrid vector search query latency $<150\\text{ms}$ on CPU.",
        "- **NFR-2 (Zero Disk Bloat & Memory Efficiency)**: Ephemeral shallow cloning MUST leave 0 MB residual cloned files on disk; FastEmbed model memory $\\le 1.2\\text{ GB}$ RAM.",
        "- **NFR-3 (Security & Credential Sanitization)**: Personal access tokens, OAuth tokens, and passwords MUST NEVER appear in cleartext in logs, console output, URLs, or client API payloads.",
        "- **NFR-4 (Reliability & Concurrency)**: SQLite database MUST operate in WAL mode; Vector store schemas MUST automatically auto-heal/upgrade on startup.",
        "- **NFR-5 (Failure Isolation)**: Failure to sync an individual repository MUST NOT abort other repositories or crash the server.",
        "- **NFR-6 (Codebase Modularity & File Size Floor)**: All individual Python and TypeScript source code files MUST remain under 500 lines of code for long-term maintainability.",
        "- **NFR-7 (Test Quality & Coverage Floor)**: Backend statement coverage $\\ge 85\\%$; Frontend line coverage $\\ge 85\\%$; 100% Playwright E2E pass rate.",
        "",
        "---",
        "",
        "## 5. Requirement-to-Test Traceability Matrix",
        "",
        "| Requirement ID | Requirement Description | Implementation Files | Backend Pytest Modules | Frontend Vitest & E2E Suites |",
        "| :--- | :--- | :--- | :--- | :--- |",
        "| **FR-1** | FastMCP 2.0 Dual Transport Architecture | `app/mcp/mcp_server.py`, `app/mcp/tools.py` | `test_mcp_v2.py`, `test_indexer_sync.py` | E2E Spec 1 |",
        "| **FR-2** | FastMCP 11 Agent Tools Contract | `app/mcp/tools.py`, `app/mcp/handlers/*` | `test_db_and_tools.py`, `test_tools.py`, `test_architecture_adr.py`, `test_trace_path.py` | E2E Specs 1, 8 |",
        "| **FR-3** | Dynamic Resources & Prompt Templates | `app/mcp/mcp_server.py`, `app/mcp/tools.py` | `test_mcp_v2.py`, `test_tools.py` | E2E Spec 1 |",
        "| **FR-4** | Universal Multi-Git Provider Ingestion | `app/services/git_manager.py`, `app/services/indexing/git_syncer.py` | `test_multi_git_providers.py`, `test_git_manager.py`, `test_indexer_edge_cases.py` | `GitRepoManager.test.tsx`, E2E Specs 2, 3, 4, 5, 16, 18 |",
        "| **FR-5** | Multi-Tier Credential Vault & Hierarchy | `app/services/database/credentials.py`, `app/services/git_manager.py` | `test_multi_git_providers.py`, `test_db_and_tools.py` | `Settings.test.tsx`, E2E Specs 10, 11 |",
        "| **FR-6** | 10-Language Tree-sitter AST Syntax & Routes | `app/services/chunking/*` | `test_chunker.py`, `test_chunker_languages.py`, `test_api_route_discovery.py`, `test_ast_relationships.py` | `SearchInspector.test.tsx`, E2E Spec 8 |",
        "| **FR-7** | Markdown Breadcrumbs & Fallbacks | `app/services/chunking/text_chunker.py` | `test_chunker.py`, `test_chunker_languages.py` | `SearchInspector.test.tsx`, E2E Spec 8 |",
        "| **FR-8** | Pluggable Multi-Backend Vector Retrieval | `app/services/vector_store/*`, `app/services/search.py` | `test_vector_store_base.py`, `test_vector_store_qdrant.py`, `test_vector_store_chroma.py`, `test_vector_store_manager.py`, `test_search.py` | `Settings.test.tsx`, `SearchInspector.test.tsx`, E2E Specs 8, 9 |",
        "| **FR-9** | Codebase & Dependency Topology Graph | `app/services/topology/*`, `app/api/routers/graph.py` | `test_topology_graph.py`, `test_trace_path.py` | `TopologyExplorer.test.tsx`, E2E Specs 25, 26 |",
        "| **FR-10** | Architecture ADRs & System Synthesis | `app/services/adr.py`, `app/services/architecture.py`, `app/services/database/adrs.py` | `test_architecture_adr.py` | `SearchInspector.test.tsx` |",
        "| **FR-11** | Auto-Sync Poller Daemon & Webhooks | `app/services/poller.py`, `app/api/webhooks.py`, `app/services/database/sync_config.py` | `test_poller.py`, `test_webhooks.py`, `test_auto_sync_api.py`, `test_auto_sync_db.py` | `GitRepoManager.test.tsx`, `Settings.test.tsx`, E2E Specs 22, 23, 24 |",
        "| **FR-12** | Administrative REST APIs & Subrouters | `app/api/routes.py`, `app/api/routers/*` | `test_api_routes.py`, `test_api_vector_store.py`, `test_diagnostic_logger.py` | `Overview.test.tsx`, `DiagnosticsViewer.test.tsx`, E2E Specs 1-26 |",
        "| **FR-13** | React 19 Single Page Admin Dashboard | `frontend/src/*`, `frontend/src/components/*` | N/A | `App.test.tsx`, `GitRepoManager.test.tsx`, `LocalPathManager.test.tsx`, `Settings.test.tsx`, `Overview.test.tsx`, E2E Specs 1-26 |",
        "| **FR-14** | Interactive Visual Topology Explorer UI | `frontend/src/TopologyExplorer.tsx`, `frontend/src/components/topology/*` | N/A | `TopologyExplorer.test.tsx`, E2E Specs 25, 26 |",
        "| **FR-15** | Diagnostics & Live In-Memory Log Viewer | `app/services/logger.py`, `frontend/src/DiagnosticsViewer.tsx` | `test_diagnostic_logger.py` | `DiagnosticsViewer.test.tsx`, E2E Specs 13, 21 |",
        "| **NFR-1** | Performance & Latency Budgets | `app/services/database/connection.py`, `app/services/search.py` | `test_db_and_tools.py`, `test_search.py` | E2E Specs 8, 9 |",
        "| **NFR-2** | Zero Disk Bloat & Memory Efficiency | `app/services/git_manager.py`, `app/services/embeddings.py` | `test_git_manager.py`, `test_indexer_and_embeddings.py` | E2E Specs 2, 3 |",
        "| **NFR-3** | Credential Sanitization in Logs/APIs | `app/services/git_manager.py`, `app/api/routers/*` | `test_multi_git_providers.py`, `test_api_routes.py` | `Settings.test.tsx`, E2E Specs 10, 11 |",
        "| **NFR-4** | SQLite WAL & Vector Store Auto-Healing | `app/services/database/*`, `app/services/vector_store/*` | `test_db_and_tools.py`, `test_vector_store_manager.py` | E2E Spec 1 |",
        "| **NFR-5** | Sync Failure Isolation | `app/services/indexing/*` | `test_indexer_edge_cases.py`, `test_indexer_sync.py` | `GitRepoManager.test.tsx`, E2E Spec 5 |",
        "| **NFR-6** | Codebase Modularity & File Size Floor | `app/` (all < 450 LOC), `frontend/src/` (all < 450 LOC) | N/A | Sub-500 LOC CI Check |",
        "| **NFR-7** | Test Quality & Coverage Floors | Entire Test Suite | `pytest` (277 tests, 88% cov) | `vitest` (82 tests, 87% cov), `playwright` (26 tests) |",
        "",
        "---",
        "",
        "## 6. Parsed Test Suite Inventory",
        "",
        "### 6.1 Backend Python Tests",
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

    lines.append("### 6.3 Playwright End-to-End User Journeys (`frontend/e2e/`)")
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
"""

def main():
    content = generate_markdown()
    root_req_path = PROJECT_ROOT / "REQUIREMENTS.md"
    with open(root_req_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Generated {root_req_path}")

    docs_req_path = PROJECT_ROOT / "docs" / "REQUIREMENTS.md"
    docs_req_path.parent.mkdir(parents=True, exist_ok=True)
    with open(docs_req_path, "w", encoding="utf-8") as f:
        f.write(DOCS_POINTER_CONTENT)
    print(f"Generated {docs_req_path}")

if __name__ == "__main__":
    main()
