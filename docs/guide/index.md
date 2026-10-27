# Overview of ContextCortex

ContextCortex is a Model Context Protocol (MCP) server for syntax-aware code search and repository intelligence. It connects AI coding assistants to local codebases, documentation, and architecture records.

ContextCortex uses the official Model Context Protocol Python SDK 2.0 (`FastMCP`). The server provides dual communication channels: Server-Sent Events (SSE) and Streamable HTTP, along with a zero-allocation JSON-RPC `ping` health interceptor.

---

## Purpose

Artificial intelligence agents require fast and accurate context to write reliable code. Traditional keyword or fixed-window search methods do not preserve code syntax boundaries or caller-callee relationship structures.

ContextCortex solves this problem:
1. It parses source files into Abstract Syntax Trees (AST) with Tree-sitter across 10 programming languages.
2. It extracts functions, classes, parameter signatures, REST API routes, and call relationships into relational tables.
3. It stores text and code chunks in vector databases with both dense semantic embeddings (`384d` BGE-Small) and sparse lexical embeddings (`BM25`).

---

## Key Capabilities

### Syntax-Aware AST Code Search
The system chunks source code along function, class, and method boundaries. Each chunk preserves 1-indexed line numbers, symbol names, parameter signatures, and Git permalinks.

### Dual Relational Architecture
The persistence layer supports PostgreSQL 16 with `pgvector` for production deployments and SQLite with Write-Ahead Logging (WAL) for zero-dependency local operation.

### Calibrated Hybrid Vector Retrieval
ContextCortex connects to Qdrant, ChromaDB, and PostgreSQL `pgvector`. Queries support `hybrid`, `semantic`, and `lexical` modes with a configurable `dense_weight` (`0.0` to `1.0`, default `0.5`) and transparent score decomposition (`dense_score` and `sparse_score`).

### Universal Git Ingestion & Shallow Retention
The system indexes repositories from GitHub, GitLab, Gitea, Forgejo, Bitbucket, and generic Git hosts. Administrators can choose between ephemeral shallow clones (`--depth 1`, deleted after indexing) and persistent shallow clones (`keep_shallow`) for instant full-file inspection and fast delta fetches.

### Managed Local Storage & PDF Vision OCR
Users can upload source files, Markdown notes, and PDF documents directly to managed storage (`/app/data/storage`). The system indexes text immediately, auto-summarizes large files (`> 500 KB`), and extracts text from scanned PDFs and diagrams with AI vision OCR fallback.

### Codebase Navigator & Omni-Search
A hero split-view interface provides per-repository file trees, AST symbol outlines, interactive breadcrumb navigation, syntax-highlighted source code viewing, GitHub Flavored Markdown + Mermaid rendering, caller/callee impact analysis, and a global `Ctrl+K` / `Cmd+K` Omni-Search command palette.

### Security and Access Control
The server supports OAuth 2.1 Protected Resource discovery (RFC 9728) and SHA-256 hashed `cc_` API keys. It enforces role-based access control across three privilege tiers: `viewer` (Level 10), `editor` (Level 20), and `admin` (Level 30).

### Enterprise Private-CA Gateways & Restricted-Network Builds
ContextCortex natively supports corporate and restricted-network environments:
- **Custom Gateway Base URLs & Request Headers**: Preserves custom OpenAI-compatible gateway URL paths (such as `/api/v3`) across model discovery, embeddings, file summarization, and PDF vision OCR, and attaches CR/LF-validated JSON headers (`LLM_EXTRA_HEADERS`) on every outbound gateway request.
- **Dual-Phase Private CA Trust**: Installs PEM certificates (`certs/*.crt` / `EXTRA_CA_CERTS_DIR`) into the container trust store at both build time (`Dockerfile`, `Dockerfile.overlay`) and runtime (`docker-entrypoint.sh`).
- **Private Mirrors & Image Overlays**: Supports internal Debian/apt, PyPI, and npm package mirrors with 30-day quarantine compatibility, or fast CA-only image overlays (`Dockerfile.overlay`, `docker-compose.enterprise.yml`) on pre-built `ghcr.io/spelech/contextcortex` images.

---

## Documentation Roadmap

- **[Getting Started](/guide/getting-started)**: Install ContextCortex via automated setup scripts, manual virtual environments, or Docker Compose.
- **[Configuration](/guide/configuration)**: Configure environment variables, database profiles, vector stores, and LiteLLM model discovery.
- **[Restricted-Network Builds](/guide/enterprise-build)**: Configure private CA certificates, internal package mirrors (`APT_MIRROR`, `PIP_INDEX_URL`, `NPM_REGISTRY`), and verified local image overlays.
- **[User Guide](/guide/user-guide)**: Explore all 9 Web Admin Dashboard modules with step-by-step instructions and screenshots.
- **[System Architecture](/architecture/)**: Review component diagrams, AST ingestion pipelines, MCP protocol flows, and database ERDs.
- **[Reference Manual](/reference/mcp-tools)**: Inspect all 16 MCP tools, dynamic resources, guided prompts, and Admin REST API endpoints.
