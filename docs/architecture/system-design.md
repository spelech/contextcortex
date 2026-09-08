# System Design and Components

This document describes the runtime components of ContextCortex and their interactions.

## High-Level System Flowchart

The following diagram illustrates the system boundaries, client interfaces, core services, and storage engines:

```mermaid
flowchart TD
    subgraph Clients["Clients and Consumers"]
        Claude["AI Coding Agents\n(Cursor, Claude Desktop, Antigravity)"]
        Browser["Web Admin Dashboard\n(React 19 Frontend)"]
    end

    subgraph Gateway["FastAPI and FastMCP Gateway"]
        FastAPI["FastAPI Core Engine"]
        AuthLayer["Authentication and RBAC Layer\n(app/services/auth/)"]
        FastMCP["FastMCP 2.0 Server\n(app/mcp/mcp_server.py)"]
        SSE["SSE Transport\n(/sse, /messages/)"]
        HTTP["Streamable HTTP Transport\n(/mcp)"]
        RFC9728["OAuth 2.1 Metadata\n(/.well-known/oauth-protected-resource)"]
        AdminAPI["Admin REST API Routers\n(app/api/routers/*)"]
        LogBuffer["Diagnostic Ring Buffer\n(app/services/logger.py)"]
    end

    subgraph CoreServices["Core Modular Services"]
        GitMgr["Universal Git Ingestion\n(app/services/git_manager.py)"]
        TSLoader["Tree-sitter AST Loader\n(app/services/chunking/)"]
        EmbeddingSrv["Embedding Engine\n(app/services/embeddings.py)"]
        SearchSrv["Hybrid Search and RRF\n(app/services/search.py)"]
        NavigatorSrv["3-Pane Codebase Navigator\n(app/services/navigator.py)"]
        StorageSrv["Local Storage Service\n(app/services/local_storage.py)"]
        PdfExtractor["PDF Extraction and OCR\n(app/services/pdf_extractor.py)"]
    end

    subgraph StorageLayer["Pluggable Storage Layer"]
        RelationalDB[("SQLAlchemy 2.0 Unified DB\n(PostgreSQL 16 / SQLite WAL)")]
        VectorDB[("Vector Storage Engines\n(Qdrant / pgvector / ChromaDB)")]
        ManagedDisk[("Managed Local Disk\n(/app/data/storage)")]
    end

    Claude -->|Bearer Token / API Key| SSE
    Claude -->|Bearer Token / API Key| HTTP
    Claude -->|OAuth Discovery| RFC9728

    SSE --> AuthLayer
    HTTP --> AuthLayer
    AuthLayer --> FastMCP

    Browser -->|REST API /admin/api/*| AdminAPI
    AdminAPI --> AuthLayer
    AdminAPI --> NavigatorSrv
    AdminAPI --> SearchSrv
    AdminAPI --> StorageSrv
    AdminAPI --> LogBuffer

    FastMCP --> SearchSrv
    FastMCP --> NavigatorSrv
    FastMCP --> GitMgr
    FastMCP --> StorageSrv

    GitMgr --> TSLoader
    StorageSrv --> PdfExtractor
    PdfExtractor --> EmbeddingSrv
    TSLoader --> EmbeddingSrv

    EmbeddingSrv --> VectorDB
    SearchSrv --> VectorDB
    NavigatorSrv --> RelationalDB
    AdminAPI --> RelationalDB
    StorageSrv --> ManagedDisk
```

---

## Component Breakdown

### 1. Client Layer
- **MCP Clients**: AI agents communicate via JSON-RPC over Server-Sent Events (SSE) or Streamable HTTP.
- **Admin Dashboard**: React 19 single-page application communicating over standard REST API endpoints.

### 2. Gateway and Security Layer
- **FastAPI Lifespan Session Manager**: Manages application startup, database migrations, connection pool initialization, and graceful shutdown.
- **Authentication Layer**: Intercepts requests, validates OAuth 2.1 JWT tokens and API keys, and enforces role-based permission checks.
- **Diagnostic Ring Buffer**: Captures the last 500 server events, errors, and traces in memory.

### 3. Core Processing Services
- **Universal Git Manager**: Handles authenticated shallow repository clones across GitHub, GitLab, Gitea, and Bitbucket.
- **Tree-sitter Chunking Package**: Parses 10 major programming languages and extracts AST nodes, API routes, and call references.
- **Embedding Engine**: Generates 384-dimensional dense vectors (FastEmbed BGE-small) and BM25 sparse vectors.
- **Search Engine**: Merges dense cosine similarity and sparse BM25 scores using Reciprocal Rank Fusion (RRF).
- **PDF Extraction Service**: Extracts text from PDF files with automated AI vision OCR fallback for embedded diagrams.
