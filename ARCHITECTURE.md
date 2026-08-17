# Architecture: Notes & Code RAG MCP Server (v2.4.1)

The Notes & Code RAG MCP Server provides fast, local, syntax-aware semantic and hybrid search over codebases, git repositories, markdown notes, and system documentation. It is built natively on the **Model Context Protocol (MCP) SDK 2.0.0+** using `FastMCP`, with an integrated FastAPI web engine, real-time diagnostic logging, and a React 19 administrative dashboard.

---

## 🏗️ High-Level System Architecture

```mermaid
flowchart TD
    subgraph Clients["MCP & Web Clients"]
        Claude["AI Coding Agents / MCP Clients (Cursor, Claude Desktop, Antigravity)"]
        Browser["Admin Dashboard (React 19 + TypeScript)"]
    end

    subgraph Server["FastAPI Core & FastMCP 2.0 Application (main.py)"]
        FastAPI["FastAPI App (Lifespan Session Manager)"]
        FastMCP["FastMCP Server (app/mcp/mcp_server.py)"]
        SSE["SSE Transport (/sse, /messages/)"]
        HTTP["Streamable HTTP Transport (/mcp)"]
        AdminAPI["Admin REST API Router (app/api/routes.py)"]
        LogBuffer["Diagnostic Ring Buffer (app/services/logger.py)"]
    end

    subgraph CoreEngine["Core Engine (app/services)"]
        Chunker["Tree-sitter AST Chunker (chunker.py)"]
        Embeddings["FastEmbed Engine (embeddings.py)\nDense (384d) + Sparse BM25"]
        GitMgr["Ephemeral Shallow Git Ingestion (git_manager.py)"]
        Indexer["Incremental Indexer (indexer.py)"]
        Search["RRF Hybrid Search (search.py)"]
        DB["SQLite DB & Symbol Registry (db.py)"]
    end

    subgraph PersistentStorage["Persistent Storage"]
        Qdrant["Qdrant Vector DB (Named Vectors: dense + sparse)"]
        SQLite["SQLite Index Cache (index_cache.db)"]
    end

    Claude -->|SSE /sse & /messages/| SSE
    Claude -->|Streamable HTTP /mcp| HTTP
    SSE --> FastMCP
    HTTP --> FastMCP

    Browser -->|REST API /admin/api/*| AdminAPI
    AdminAPI --> DB
    AdminAPI --> Indexer
    AdminAPI --> LogBuffer
    AdminAPI --> Search

    FastMCP --> Search
    FastMCP --> Chunker
    FastMCP --> DB
    FastMCP --> Indexer

    Indexer --> Chunker
    Indexer --> Embeddings
    Indexer --> GitMgr
    Indexer --> Qdrant
    Indexer --> SQLite
    Indexer --> LogBuffer

    Search --> Embeddings
    Search --> Qdrant
```

---

## 🧩 Core Architecture Components

### 1. FastMCP 2.0 Server & Transport Routing (`app/mcp/`)
- **FastMCP Foundation**: Implemented via `mcp.server.fastmcp.FastMCP` with lifespan session management (`mcp_server.session_manager.run()`).
- **Dual MCP Transports**:
  - **Server-Sent Events (SSE)**: Mounted via `mcp_server.sse_app().routes`, handling streaming events at `/sse` and message exchanges at `/messages/`.
  - **Streamable HTTP**: Mounted via `mcp_server.streamable_http_app().routes` at `/mcp` for direct bidirectional JSON-RPC.
- **Agent Tools (7 Tools)**:
  - `search_code`: Hybrid semantic + BM25 search over code functions and logic blocks with line numbers and GitHub links.
  - `search_docs`: Dedicated hybrid search across markdown notes, system architecture, and runbooks.
  - `find_symbol`: Instant exact/fuzzy symbol definitions from AST index.
  - `get_file_outline`: File symbol hierarchy without full token context costs.
  - `list_repositories`: Summary of all indexed Git repos and local paths.
  - `sync_repository`: On-demand re-sync for a specific repo or all sources.
  - `index_status`: Global vector stats, model metadata, and GitHub rate limits.
- **Dynamic Resource Providers**:
  - `notes://catalog/summary`: Markdown catalog summarizing indexed repositories, file counts, and AST symbol distributions.
- **Custom Agent Prompt Templates**:
  - `search_infrastructure_docs`: Parameterized workflow for infrastructure and deployment queries.
  - `find_implementation_symbol`: Parameterized workflow for locating implementation symbols.

---

### 2. Diagnostic Logging & System Observability (`app/services/logger.py`)
- **In-Memory Ring Buffer**: Implemented using `collections.deque(maxlen=500)` guarded by a `threading.Lock()`.
- **Diagnostic Log Handler**: Captures log records across all backend modules (`notes-rag-mcp`, `server.*`, `indexer`, `git`, `ast_parser`), preserving:
  - `timestamp`: ISO-8601 UTC timestamp.
  - `level`: `INFO`, `WARNING`, `ERROR`, `DEBUG`.
  - `logger`: Originating logger name.
  - `message`: Formatted log message.
  - `traceback`: Full exception stack trace when available.
- **REST Endpoints**:
  - `GET /admin/api/logs`: Retrieves formatted log records with level filtering and search query support.
  - `DELETE /admin/api/logs`: Atomically clears the ring buffer.

---

### 3. AST Code & Documentation Parsing Engine (`app/services/chunker.py`)
- **Tree-sitter AST Parser**: Parses syntactic structures across Python, TypeScript, JavaScript, Go, Rust, C#, C++, Java, Ruby, PHP, and more.
- **Boundary-Aware Chunking**: Chunks along class, method, function, and struct boundaries with exact line numbers and symbol names.
- **Contextual Markdown Chunker**: Chunks documentation files by header hierarchies (`#`, `##`, `###`) with breadcrumb enrichment.
- **Graceful Fallback**: Text-based fallback chunker for unsupported languages and malformed syntax.

---

### 4. Hybrid Embedding & Vector Engine (`app/services/embeddings.py`, `app/services/search.py`)
- **Named Multi-Vectors**: Qdrant collections configured with dual vector spaces:
  - **Dense Vectors**: `BAAI/bge-small-en-v1.5` (384 dimensions, Cosine distance).
  - **Sparse Vectors**: `Qdrant/bm25` (In-process FastEmbed BM25 sparse model).
- **Reciprocal Rank Fusion (RRF)**: Merges dense semantic similarity with sparse keyword retrieval using reciprocal rank fusion ($RRF\_score = \sum \frac{1}{60 + rank}$) for optimal search recall.
- **Local In-Process Execution**: ONNX runtime execution on CPU with zero external API latency or cost.

---

### 5. Universal Git Repository Ingestion (`app/services/git_manager.py`)
- **Universal Provider Support**:
  - Automatically identifies or configures providers: **GitHub**, **GitLab (Cloud, Enterprise & Self-Hosted)**, **Gitea & Forgejo**, **Bitbucket (Cloud & Server)**, and **Generic Git HTTP/HTTPS**.
  - Custom ports, local IPs, and self-hosted instances supported (e.g. `http://git.lan:3000/user/repo.git`).
- **Shallow Cloning**: Authenticated shallow clones (`git clone --depth 1 --branch <branch> --single-branch`) into temporary directories.
- **Remote SHA Tracking**: Queries remote commit SHAs via `git ls-remote` to skip redundant clones.
- **Zero Disk Bloat**: Prunes cloned directories immediately after AST extraction and vector upserts.
- **Provider-Exact Permalinks**:
  - GitHub: `{base}/blob/{sha}/{path}#L{start}-L{end}`
  - GitLab: `{base}/-/blob/{sha}/{path}#L{start}-{end}`
  - Gitea / Forgejo: `{base}/src/commit/{sha}/{path}#L{start}-L{end}`
  - Bitbucket: `{base}/src/{sha}/{path}#lines-{start}:{end}`
- **Multi-Tier Git Authentication Hierarchy**:
  1. Per-repository override token & optional username (`auth_token`, `auth_user`).
  2. Domain-level Custom Git Host Vault (`git_host_credentials`).
  3. Global provider tokens (`GITHUB_TOKEN`, `GITLAB_TOKEN`, `GITEA_TOKEN` in DB or Settings UI).
  4. Environment variable fallback.
- **Credential Masking & URL Sanitization**: Complete redaction of all passwords and tokens from log messages and UI payloads.

---

### 6. Database & Symbol Index (`app/services/db.py`)
- **SQLite Database (`index_cache.db`) with WAL mode**:
  - `git_repositories`: Registered remote Git repos, provider type, auth usernames, branches, commit SHAs, status, and last synced timestamps.
  - `git_host_credentials`: Host domain credential vault for self-hosted instances.
  - `indexed_paths`: Monitored local directories and files.
  - `ast_symbols`: Indexed symbol table (classes, functions, methods, line numbers, signatures) for instantaneous `find_symbol` and `get_file_outline`.
  - `indexed_files` & `file_summaries`: File metadata, mtime change detection, and topic tags.
  - `system_metadata`: Key-value storage for tokens and timestamps.

#### SQLite Relational Entity-Relationship Diagram (ERD)
```mermaid
erDiagram
    GIT_REPOSITORIES {
        int id PK
        string name UK "Repository alias"
        string url "Clone URL"
        string branch "Branch name"
        string provider "github | gitlab | gitea | bitbucket | generic"
        string auth_user "Optional auth username"
        string auth_token "Optional repo override token"
        string commit_sha "Latest indexed commit SHA"
        string status "pending | syncing | synced | error"
        string last_error "Error message if failed"
        string last_synced "ISO-8601 Timestamp"
        int enabled "1 = Active, 0 = Disabled"
        datetime added_at "Creation timestamp"
    }

    GIT_HOST_CREDENTIALS {
        int id PK
        string host UK "Domain / IP:Port"
        string provider "gitlab | gitea | github | bitbucket | generic"
        string auth_user "Optional default user"
        string auth_token "Host access token / password"
        datetime added_at "Creation timestamp"
    }

    INDEXED_PATHS {
        int id PK
        string path UK "Absolute filesystem path"
        string type "directory | file"
        int recursive "1 = Yes, 0 = No"
        int enabled "1 = Active, 0 = Disabled"
        string category "architecture | guides | notes"
        string repo "Assigned repo alias"
        datetime added_at "Creation timestamp"
    }

    INDEXED_FILES {
        string filepath PK "Path within repo or local vault"
        string repo "Repository or vault alias"
        string doc_type "code | doc"
        string language "python | typescript | markdown | ..."
        string commit_sha "Commit SHA when indexed"
        real mtime "Filesystem modification time"
        string hash "Content SHA256 hash"
    }

    AST_SYMBOLS {
        int id PK
        string repo "Repository alias"
        string filepath "Relative file path"
        string kind "class | function | method | interface | struct"
        string name "Symbol identifier name"
        string full_symbol "Qualified symbol path"
        string signature "Parameter signature"
        int start_line "1-indexed start line"
        int end_line "1-indexed end line"
        string language "Language grammar identifier"
    }

    FILE_SUMMARIES {
        string filepath PK "Relative or local path"
        string repo "Repository alias"
        string title "Extracted title or basename"
        string folder "Parent directory name"
        string category "Documentation category"
        string tags "JSON list of tags"
        string headings "JSON list of headings"
        string keywords "JSON list of keywords"
        real mtime "Modification timestamp"
    }

    SYSTEM_METADATA {
        string key PK "Key identifier"
        string value "String value"
    }

    GIT_REPOSITORIES ||--o{ INDEXED_FILES : "contains"
    GIT_REPOSITORIES ||--o{ AST_SYMBOLS : "declares"
    GIT_REPOSITORIES ||--o{ FILE_SUMMARIES : "summarizes"
    INDEXED_PATHS ||--o{ INDEXED_FILES : "contains"
    INDEXED_FILES ||--o{ AST_SYMBOLS : "defines"
    INDEXED_FILES ||--o| FILE_SUMMARIES : "has metadata"
```

#### Qdrant Hybrid Vector Store Schema
```mermaid
classDiagram
    class QdrantCollection {
        +String collection_name "notes_rag_v2"
        +DenseVectorParams dense (384d, Cosine)
        +SparseVectorParams sparse (BM25)
    }

    class VectorPoint {
        +UUID id "UUID5(namespace, repo:filepath#index)"
        +List~Float~ dense_vector [384 floats]
        +Map~Int,Float~ sparse_vector [BM25 weights]
        +PointPayload payload
    }

    class PointPayload {
        +String repo "Keyword index: repo alias"
        +String path "Keyword index: relative path"
        +String doc_type "Keyword index: code | doc"
        +String language "Keyword index: python, ts, md, etc."
        +String content "Raw chunk text"
        +Int start_line "Line start"
        +Int end_line "Line end"
        +String symbol "AST symbol name"
        +String github_url "Provider deep permalink"
        +List~String~ tags "Documentation tags"
        +String title "Doc title / heading"
        +String commit_sha "Commit SHA snapshot"
    }

    QdrantCollection *-- VectorPoint : stores
    VectorPoint *-- PointPayload : contains
```

---

### 7. Modern Web Admin Dashboard (`frontend/`)
- **React 19 + TypeScript + Vite**: Fast, reactive dashboard served at `/admin/`.
- **Tabs**:
  - **Overview**: System metrics, embedding model specs, keyword cloud, and full reindex trigger.
  - **Git Repositories**: Repository registration modal, single-repo sync triggers, error diagnostics, and deletion.
  - **Local Paths**: Workspace directory browser, path configuration, and recursive indexing toggles.
  - **Search & Inspector**: Live hybrid search tester with code/doc toggle, repo filters, and RRF score inspect.
  - **Settings**: GitHub PAT configuration and rate limit status monitor.
  - **Diagnostics & Logs**: Real-time log inspector with level pills (ALL, INFO, WARNING, ERROR, DEBUG), keyword filtering, traceback view modal, and buffer clear action.

---

## 🧪 Test Topology & Quality Assurance

```
┌─────────────────────────────────────────────────────────────┐
│                    Test Suite Topology                      │
├──────────────────────────────┬──────────────────────────────┤
│ Python Backend (Pytest)      │ Frontend (Vitest & Playwright)│
├──────────────────────────────┼──────────────────────────────┤
│ - tests/backend/test_mcp.py  │ - Vitest Unit/Component:     │
│ - tests/backend/test_api.py  │   * App.test.tsx             │
│ - tests/backend/test_*.py    │   * DiagnosticsViewer.test   │
│ - >95% statement coverage    │   * GitRepoManager.test      │
│ - FastMCP 2.0 tools/prompts  │   * SearchInspector.test     │
│ - Ring buffer logging tests  │ - Playwright E2E (13 specs): │
│ - Ephemeral git clone tests  │   * Full UI navigation       │
│ - Hybrid search & RRF tests  │   * Modals & confirmation    │
│                              │   * Real-time sync feedback  │
│                              │   * Diagnostics log viewer   │
└──────────────────────────────┴──────────────────────────────┘
```
