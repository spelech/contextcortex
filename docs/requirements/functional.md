# Functional Requirements

This section specifies the functional requirements for ContextCortex (`v2.19.0`).

---

### FR-01: Abstract Syntax Tree (AST) Code Chunking
- **Description**: The system must parse source code into Abstract Syntax Trees using Tree-sitter.
- **Languages Supported**: Python, TypeScript, JavaScript, Go, Rust, C#, C++, Java, Ruby, and PHP.
- **Behavior**: The parser must chunk along function, class, and method boundaries. Chunks must preserve symbol names, parameter signatures, and 1-indexed line numbers.
- **Maximum Chunk Size**: When a symbol exceeds 512 tokens, child blocks must be segmented while preserving the parent declaration header.

---

### FR-02: Calibrated Hybrid Dense and Sparse Vector Retrieval
- **Description**: The system must support hybrid vector search combining semantic similarity and lexical keyword matching.
- **Embedding Generation**: The system must generate 384-dimensional dense vectors (`FastEmbed BAAI/bge-small-en-v1.5` or upstream LiteLLM/OpenAI API embeddings) and lexical sparse vectors (`BM25`).
- **Calibrated Scoring & Modes**: Search queries must support `hybrid`, `semantic`, and `lexical` modes with a configurable `dense_weight` (`0.0` to `1.0`, default `0.5`), expose decomposed `dense_score` and `sparse_score` metrics, and enrich code hits with AST signatures from `ast_symbols`.

---

### FR-03: Dual Relational Storage Engines
- **Description**: The system must maintain relational metadata using SQLAlchemy 2.0 Core unified schemas.
- **PostgreSQL 16 Engine**: Production containerized mode with pooled connections (`psycopg3`) and native `vector(384)` HNSW indexing.
- **SQLite WAL Engine**: Zero-configuration embedded disk mode with automatic Write-Ahead Logging and a 15000ms busy timeout.

---

### FR-04: Pluggable Vector Store Backends
- **Description**: The system must support dynamic vector database adapters without server restarts.
- **Engines Supported**: Qdrant (remote server and embedded disk), PostgreSQL `pgvector`, and ChromaDB.
- **Runtime Switching**: Administrators must be able to test connection health and switch active vector backends via the Settings interface or REST API (`/admin/api/vector-store/switch`).

---

### FR-05: Universal Git Provider Synchronization & Shallow Retention
- **Description**: The system must ingest remote Git repositories from GitHub, GitLab, Gitea, Forgejo, Bitbucket, and generic Git hosts.
- **Configurable Shallow Clones (`keep_shallow`)**: The system must support both ephemeral shallow clones (`--depth 1`, deleted immediately after extraction to conserve disk storage) and persistent shallow clones (`keep_shallow=1` in `/app/data/repos/{repo_name}`) for full-file inspection and fast delta fetches.
- **Custom Credential Vault**: The system must store domain-level Git host tokens for internal and self-hosted instances.

---

### FR-06: Managed Local Storage, File Reading & Summarization
- **Description**: The system must provide a managed local storage directory (`/app/data/storage`) for uploaded files and safe reading across indexed sources.
- **Security**: The system must sanitize all file paths using canonical containment checks to prevent directory traversal attacks (rejection of `..`, leading slashes, and null bytes).
- **Immediate Indexing & Summarization**: Uploaded and modified files must be indexed immediately. Files exceeding the size threshold (default `500 KB`) must be summarized via the configured LLM (`summarize_file`) and readable via bounded line ranges (`read_file`).

---

### FR-07: PDF Document Ingestion with Vision OCR Fallback
- **Description**: The system must process PDF documents up to 50 megabytes in size.
- **Text Extraction**: The system must extract digital text layers using `pypdf`.
- **Vision OCR Fallback**: When pages contain minimal digital text or complex technical diagrams, the system must trigger optical character recognition using the configured LiteLLM vision model.
- **Preview Modal**: The system must present an interactive preview showing extracted text, sample chunks, and OCR flags before committing to vector storage.

---

### FR-08: Model Context Protocol (MCP) 2.0 Compliance & 16 Tools
- **Description**: The system must implement the official Model Context Protocol using `FastMCP` 2.0.
- **Transports & Liveness**: The system must provide Server-Sent Events (SSE) at `/sse` (with `/messages/`), Streamable HTTP at `/mcp`, and zero-allocation JSON-RPC `ping` interception via `McpPingMiddleware`.
- **Tools**: The system must expose **16 dedicated agent tools**: `search_code`, `search_docs`, `find_symbol`, `trace_path`, `find_routes`, `find_api_callers`, `get_file_outline`, `list_repositories`, `sync_repository`, `index_status`, `get_architecture`, `manage_adr`, `manage_local_file`, `what_is_ingested`, `read_file`, and `summarize_file`.

---

### FR-09: RFC 9728 OAuth 2.1 and 3-Tier RBAC
- **Description**: When `AUTH_ENABLED=true`, the server must act as an RFC 9728 OAuth 2.1 Protected Resource Server.
- **Metadata Endpoint**: The server must expose authorization metadata at `GET /.well-known/oauth-protected-resource`.
- **Roles**: The system must enforce three permission tiers: Viewer (Level 10), Editor (Level 20), and Admin (Level 30).
- **API Keys**: The system must authenticate requests bearing `cc_` API keys verified against SHA-256 database hashes.

---

### FR-10: Hero Split Codebase Navigator & Omni-Search
- **Description**: The web dashboard must provide an interactive hero split-view architectural navigator and global command palette.
- **Left Sidebar (Files & Symbols)**: Dual-tab sidebar with per-repository folder expansion persistence (`sessionStorage`), AST symbol outline, and category chip filters (`All`, `Functions`, `Classes`, `Routes`).
- **Omni-Search (`Ctrl+K` / `Cmd+K`)**: Floating command palette providing fuzzy search across repositories, file paths, AST symbols, and API routes.
- **Center Hero Viewport**: Full syntax-highlighted source code viewer with target line-range highlighting, GFM + Mermaid document reader, breadcrumb bar, and instant Caller/Callee Impact Inspector.

---

### FR-11: AI Gateway & Dynamic LiteLLM Model Discovery
- **Description**: The system must discover and classify available models from configured LiteLLM or OpenAI-compatible proxy endpoints (`/admin/api/models/discover`).
- **Versioned URL & Extra Headers**: The system must preserve custom gateway path prefixes (e.g., `/api/v3/models`) and inject CR/LF-validated custom HTTP headers from `LLM_EXTRA_HEADERS` across model discovery, embeddings, file summarization, and PDF vision OCR without allowing custom headers to clobber resolved `Authorization` bearer credentials.
- **Categorization**: Models must be sorted into Embedding Models, Vision OCR Models, and Chat Models based on model identifiers and capabilities.
- **Persistence**: Selected AI Gateway and embedding configurations must be persisted to the system metadata database and dynamically applied without requiring a container restart.

---

### FR-12: Diagnostic Observability and Ring Buffer
- **Description**: The system must maintain an in-memory ring buffer of the 500 most recent logging events.
- **REST Interface**: Logs must be accessible via `GET /admin/api/logs` with level filtering (`ALL`, `INFO`, `WARNING`, `ERROR`, `DEBUG`) and keyword search.
- **Traceback Viewer**: The UI must display interactive error tracebacks and allow one-click buffer reset.

---

### FR-13: Unified Ingestion Catalog
- **Description**: The system must provide a unified view of all indexed sources via `what_is_ingested` and `GET /admin/api/ingestion/catalog`.
- **Filtering**: Users can filter sources by type (`git`, `monitored_path`, `local_storage`), repository name, path prefix, and file extension.

---

### FR-14: Architectural Decision Records (ADR)
- **Description**: The system must parse and track Architectural Decision Records (MADR format).
- **Operations**: Agents can query, create, update, and supersede ADRs via `manage_adr`.

---

### FR-15: Multi-Theme User Interface
- **Description**: The Web Admin Dashboard must provide four visual palettes (Deep Ocean, Midnight Blue, Lavender Haze, Amber Warmth).
- **Responsiveness**: The UI must support desktop and mobile viewport dimensions without horizontal content overflow.

---

### FR-16: Enterprise Private-CA Trust & Restricted-Network Deployment
- **Description**: The container build and runtime environment must support corporate TLS inspection, private certificate authorities, and internal package mirrors.
- **Build & Runtime CA Bootstrap**: Custom PEM certificates (`certs/*.crt` / `EXTRA_CA_CERTS_DIR`) must be added to the system trust bundle at build time (`Dockerfile`, `Dockerfile.overlay`) and synchronized at container start (`docker-entrypoint.sh`) with stale-certificate cleanup and fail-closed verification.
- **Mirror & Overlay Support**: Container builds must accept `APT_MIRROR`, `NPM_REGISTRY`, `PIP_INDEX_URL`, `PIP_EXTRA_INDEX_URL`, `PIP_TRUSTED_HOST`, and base image overrides (`NODE_BASE_IMAGE`, `PYTHON_BASE_IMAGE`).
