# Architecture: ContextCortex (v2.11.0)

ContextCortex provides fast, local, syntax-aware semantic and hybrid search over codebases, git repositories, markdown notes, architecture documents, and system documentation. It is built natively on the **Model Context Protocol (MCP) SDK 2.0.0+** using `FastMCP`, with an integrated FastAPI web engine, real-time diagnostic logging, pluggable vector store backends (Qdrant & ChromaDB), automatic polling daemons, multi-provider webhooks, interactive dependency topology graph explorer, and a React 19 administrative dashboard.

All backend services and frontend components are modularized into cohesive packages with a strict **sub-500 LOC per file** maintainability floor.

---

## 🏗️ High-Level System Architecture

```mermaid
flowchart TD
    subgraph Clients["MCP & Web Clients"]
        Claude["AI Coding Agents / MCP Clients (Cursor, Claude Desktop, Antigravity)"]
        Browser["Admin Dashboard (ContextCortex Dashboard - React 19)"]
    end

    subgraph Server["FastAPI Core & FastMCP 2.0 Application (main.py)"]
        FastAPI["FastAPI App (Lifespan Session Manager)"]
        FastMCP["FastMCP Server (app/mcp/mcp_server.py)"]
        SSE["SSE Transport (/sse, /messages/)"]
        HTTP["Streamable HTTP Transport (/mcp)"]
        AdminAPI["Admin REST API Routers (app/api/routers/*)"]
        Webhooks["Webhook Ingestion (app/api/webhooks.py)"]
        LogBuffer["Diagnostic Ring Buffer (app/services/logger.py)"]
    end

    subgraph ModularServices["Core Modular Services (app/services/)"]
        subgraph ChunkingPkg["app/services/chunking/"]
            TSLoader["tree_sitter_loader.py"]
            TextChunk["text_chunker.py"]
            SymExtract["symbol_extractor.py"]
            RelExtract["relationship_extractor.py"]
            RouteExtract["api_route_extractor.py"]
        end

        subgraph IndexingPkg["app/services/indexing/"]
            IdxState["state.py"]
            GitSync["git_syncer.py"]
            LocalSync["local_syncer.py"]
            ProcFile["processor.py"]
        end

        subgraph DatabasePkg["app/services/database/"]
            DBConn["connection.py"]
            Creds["credentials.py"]
            SyncCfg["sync_config.py"]
            ADRDb["adrs.py"]
        end

        subgraph VectorStorePkg["app/services/vector_store/"]
            VSBase["base.py"]
            VSManager["manager.py"]
            QdrantStore["qdrant_store.py"]
            ChromaStore["chroma_store.py"]
        end

        subgraph TopologyPkg["app/services/topology/"]
            GraphBuilder["graph_builder.py"]
            NodeDetails["node_details.py"]
            TopoHelpers["helpers.py"]
        end

        GitMgr["Universal Shallow Git Ingestion (git_manager.py)"]
        Embeddings["FastEmbed Engine (embeddings.py)\nDense (384d) + Sparse BM25"]
        Search["Hybrid & RRF Search (search.py)"]
        Poller["Auto-Sync Poller Daemon (poller.py)"]
        ADRService["ADR Parser & Lifecycle (adr.py)"]
    end

    subgraph PersistentStorage["Persistent Storage"]
        VectorStore["Pluggable Vector Store (Qdrant / ChromaDB)"]
        SQLite["SQLite Index Cache (index_cache.db)"]
    end

    Claude -->|SSE /sse & /messages/| SSE
    Claude -->|Streamable HTTP /mcp| HTTP
    SSE --> FastMCP
    HTTP --> FastMCP

    Browser -->|REST API /admin/api/*| AdminAPI
    Browser -->|Webhooks /api/webhooks/*| Webhooks

    AdminAPI --> DatabasePkg
    AdminAPI --> IndexingPkg
    AdminAPI --> VectorStorePkg
    AdminAPI --> TopologyPkg
    AdminAPI --> Search
    AdminAPI --> LogBuffer

    FastMCP --> Search
    FastMCP --> SymExtract
    FastMCP --> DatabasePkg
    FastMCP --> IndexingPkg
    FastMCP --> TopologyPkg
    FastMCP --> ADRService

    IndexingPkg --> ChunkingPkg
    IndexingPkg --> Embeddings
    IndexingPkg --> GitMgr
    IndexingPkg --> VectorStorePkg
    IndexingPkg --> DatabasePkg
    IndexingPkg --> LogBuffer

    Poller --> GitMgr
    Poller --> IndexingPkg
    Webhooks --> IndexingPkg

    VectorStorePkg --> VectorStore
    DatabasePkg --> SQLite

    Search --> Embeddings
    Search --> VectorStorePkg
```

---

## 🧩 Modular Architecture Packages

### 1. FastMCP 2.0 Server & Handlers (`app/mcp/`)
- **FastMCP Core (`app/mcp/mcp_server.py`)**: Manages MCP lifespan and session registration.
- **Dual Transports**:
  - **Server-Sent Events (SSE)**: Streaming events at `/sse` and message exchanges at `/messages/`.
  - **Streamable HTTP**: Bidirectional JSON-RPC at `/mcp`.
- **Extended Agent Tools (`app/mcp/tools.py` & `app/mcp/handlers/`)**:
  - `search_handlers.py`: `search_code`, `search_docs` hybrid search with RRF.
  - `symbol_handlers.py`: `find_symbol`, `get_file_outline` sub-50ms AST lookups.
  - `repo_handlers.py`: `list_repositories`, `sync_repository`, `index_status`.
  - `route_handlers.py`: `get_code_routes`, `trace_call_path` cross-repo API calls.
  - `architecture_handlers.py`: `get_architecture`, `manage_adr` ADR tracking.
- **Dynamic Resource Providers**:
  - `knowledge://catalog/summary`: Markdown catalog of repositories, document types, and symbols.
- **Agent Prompts**:
  - `search_infrastructure_docs`, `find_implementation_symbol`.

---

### 2. Multi-Language Tree-sitter AST & Chunking (`app/services/chunking/`)
- `tree_sitter_loader.py`: Lazy loader for 10 Tree-sitter grammars (Python, TS/JS, Go, Rust, C#, C++, Java, Ruby, PHP).
- `text_chunker.py`: Hierarchical markdown breadcrumbs (`# > ## > ###`) and sliding window text chunking.
- `symbol_extractor.py`: AST symbol declaration extraction with 1-indexed line numbers and signatures.
- `relationship_extractor.py`: AST relations extraction (`CALLS`, `IMPORTS`, `EXTENDS`).
- `api_route_extractor.py`: REST route definitions and client invocations across backend frameworks.

---

### 3. Incremental Ingestion & Syncing (`app/services/indexing/`)
- `state.py`: Global indexing lock, active session notifications (`send_tool_list_changed`), configuration constants.
- `git_syncer.py`: Ephemeral shallow git cloning, remote commit SHA tracking, AST symbol ingestion, vector upserts.
- `local_syncer.py`: Local filesystem directories and Obsidian markdown vault indexing with mtime caching.
- `processor.py`: Unified file parsing, YAML frontmatter extraction, and AST chunk generation.

---

### 4. Pluggable Multi-Backend Vector Layer (`app/services/vector_store/`)
- `base.py`: Abstract `VectorStore` base class and standard `VectorSearchResult` / `VectorDocument` models.
- `manager.py`: Singleton vector store provider with runtime backend switching (`/admin/api/settings/vector-store/switch`), health checks, and data migration.
- `qdrant_store.py`: Qdrant embedded (`/app/data/qdrant_storage`) and remote server (`http://qdrant:6333`) hybrid search (Dense 384d + Sparse BM25 with RRF).
- `chroma_store.py`: ChromaDB persistent disk (`/app/data/chroma_db`) and remote client storage.

---

### 5. Topology & Dependency Graph (`app/services/topology/`)
- `graph_builder.py`: Builds multi-repo dependency graphs combining files, classes, functions, and API routes with depth-bounded BFS filtering.
- `node_details.py`: Formats deep inspection data (code previews, line ranges, neighbor relations, permalinks).
- `helpers.py`: Cross-repo node ID generation, URL link normalization, and graph pruning.

---

### 6. Relational Database & Credential Vault (`app/services/database/`)
- `connection.py`: SQLite WAL connection management, automatic table migration, resilient stats count.
- `credentials.py`: Multi-tier credential hierarchy resolution and Custom Git Host Vault CRUD.
- `sync_config.py`: Auto-sync intervals and webhook secret configurations.
- `adrs.py`: Architectural Decision Record storage, search, and lifecycle status transitions.

---

### 7. Universal Git Management (`app/services/git_manager.py`)
- **Universal Provider Ingestion**: GitHub, GitLab (Cloud & Self-Hosted), Gitea/Forgejo, Bitbucket, and Generic Git HTTP/HTTPS.
- **Zero Disk Bloat**: Shallow ephemeral clones cleaned immediately after processing.
- **Provider-Exact Permalinks**: Deep code permalinks across all supported Git hosts.
- **Credential Sanitization**: URL sanitization masking tokens in logs and client responses.

---

### 8. Background Poller & Multi-Provider Webhooks
- `app/services/poller.py`: Background daemon checking remote commit SHAs at configured intervals.
- `app/api/webhooks.py`: Authenticated push event ingestion for GitHub, GitLab, Gitea, and Bitbucket.

---

## 🗄️ Relational Data Models (ERD)

```mermaid
erDiagram
    GIT_REPOSITORIES {
        int id PK
        string name UK
        string url
        string branch
        string provider
        string auth_user
        string auth_token
        string commit_sha
        string status
        string last_error
        string last_synced
        int enabled
        int auto_sync_enabled
        int auto_sync_interval
        string webhook_secret
        datetime added_at
    }

    GIT_HOST_CREDENTIALS {
        int id PK
        string host UK
        string provider
        string auth_user
        string auth_token
        datetime added_at
    }

    INDEXED_PATHS {
        int id PK
        string path UK
        string type
        int recursive
        int enabled
        string category
        string repo
        datetime added_at
    }

    INDEXED_FILES {
        string filepath PK
        string repo
        string doc_type
        string language
        string commit_sha
        real mtime
        string hash
    }

    AST_SYMBOLS {
        int id PK
        string repo
        string filepath
        string kind
        string name
        string full_symbol
        string signature
        int start_line
        int end_line
        string language
    }

    AST_RELATIONSHIPS {
        int id PK
        string repo
        int source_symbol_id
        string source_filepath
        string source_symbol
        string target_symbol
        string relationship_type
        int line_number
    }

    API_ROUTES {
        int id PK
        string repo
        string filepath
        string framework
        string http_method
        string path_pattern
        string handler_symbol
        int start_line
        int end_line
    }

    API_CLIENT_CALLS {
        int id PK
        string repo
        string filepath
        string http_method
        string url_pattern
        string caller_symbol
        int line_number
    }

    ARCHITECTURE_ADRS {
        int id PK
        string repo
        string adr_number
        string title
        string status
        string date
        string filepath
        string context
        string decision
        string consequences
        string raw_content
    }

    FILE_SUMMARIES {
        string filepath PK
        string repo
        string title
        string folder
        string category
        string tags
        string headings
        string keywords
        real mtime
    }

    SYSTEM_METADATA {
        string key PK
        string value
    }

    GIT_REPOSITORIES ||--o{ INDEXED_FILES : "contains"
    GIT_REPOSITORIES ||--o{ AST_SYMBOLS : "declares"
    GIT_REPOSITORIES ||--o{ AST_RELATIONSHIPS : "traces"
    GIT_REPOSITORIES ||--o{ API_ROUTES : "exposes"
    GIT_REPOSITORIES ||--o{ API_CLIENT_CALLS : "invokes"
    GIT_REPOSITORIES ||--o{ ARCHITECTURE_ADRS : "documents"
    GIT_REPOSITORIES ||--o{ FILE_SUMMARIES : "summarizes"
    INDEXED_PATHS ||--o{ INDEXED_FILES : "contains"
    INDEXED_FILES ||--o{ AST_SYMBOLS : "defines"
    INDEXED_FILES ||--o| FILE_SUMMARIES : "has metadata"
```
