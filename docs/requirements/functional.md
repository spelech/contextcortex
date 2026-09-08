# Functional Requirements

This section specifies the functional requirements for ContextCortex.

---

### FR-01: Abstract Syntax Tree (AST) Code Chunking
- **Description**: The system must parse source code into Abstract Syntax Trees using Tree-sitter.
- **Languages Supported**: Python, TypeScript, JavaScript, Go, Rust, C#, C++, Java, Ruby, and PHP.
- **Behavior**: The parser must chunk along function and class boundaries. Chunks must preserve symbol names, parameter signatures, and 1-indexed line numbers.
- **Maximum Chunk Size**: When a symbol exceeds 512 tokens, child blocks must be segmented while preserving the parent declaration header.

---

### FR-02: Hybrid Dense and Sparse Vector Retrieval
- **Description**: The system must support hybrid vector search combining semantic similarity and keyword matching.
- **Embedding Generation**: The system must generate 384-dimensional dense vectors using FastEmbed (`BAAI/bge-small-en-v1.5`) and lexical sparse vectors using BM25.
- **Ranking Algorithm**: The system must combine dense cosine similarity scores and sparse BM25 scores using Reciprocal Rank Fusion (RRF with $k=60$).

---

### FR-03: Dual Relational Storage Engines
- **Description**: The system must maintain relational metadata using SQLAlchemy 2.0 Core unified schemas.
- **PostgreSQL 16 Engine**: Production containerized mode with pooled connections (`psycopg3`) and native `vector(384)` HNSW indexing.
- **SQLite WAL Engine**: Zero-configuration embedded disk mode with automatic Write-Ahead Logging and a 5000ms busy timeout.

---

### FR-04: Pluggable Vector Store Backends
- **Description**: The system must support dynamic vector database adapters without server restarts.
- **Engines Supported**: Qdrant (remote server and embedded disk), PostgreSQL pgvector, and ChromaDB.
- **Runtime Switching**: Administrators must be able to test connection health and switch active vector backends via the Settings interface or REST API.

---

### FR-05: Universal Git Provider Synchronization
- **Description**: The system must ingest remote Git repositories from GitHub, GitLab, Gitea, Forgejo, Bitbucket, and generic Git hosts.
- **Ephemeral Clones**: The system must perform authenticated shallow clones (`--depth 1`), extract symbols and vectors, and immediately remove repository files from host storage.
- **Custom Credential Vault**: The system must store domain-level Git host tokens for internal and self-hosted instances.

---

### FR-06: Managed Local Storage and Real-Time Indexing
- **Description**: The system must provide a managed local storage directory (`/app/data/storage`) for uploaded files.
- **Security**: The system must sanitize all file paths to prevent directory traversal attacks (rejection of `..`, leading slashes, and null bytes).
- **Immediate Indexing**: Uploaded and modified files must be indexed into the vector store immediately. Deleted files must have their relational records and vector points purged without delay.

---

### FR-07: PDF Document Ingestion with Vision OCR Fallback
- **Description**: The system must process PDF documents up to 50 megabytes in size.
- **Text Extraction**: The system must extract digital text layers using `pypdf`.
- **Vision OCR Fallback**: When pages contain minimal digital text or complex technical diagrams, the system must trigger optical character recognition using the configured LiteLLM vision model.
- **Preview Modal**: The system must present an interactive preview showing extracted text, sample chunks, and OCR flags before committing to vector storage.

---

### FR-08: Model Context Protocol (MCP) 2.0 Compliance
- **Description**: The system must implement the official Model Context Protocol (2026-07-28) using `FastMCP`.
- **Transports**: The system must provide Server-Sent Events (SSE) at `/sse` (with `/messages/`) and Streamable HTTP at `/mcp`.
- **Tools**: The system must expose 14 dedicated agent tools (`search_code`, `search_docs`, `find_symbol`, `get_file_outline`, `list_repositories`, `sync_repository`, `index_status`, `get_architecture`, `manage_adr`, `get_code_routes`, `trace_call_path`, `manage_local_file`, `what_is_ingested`).

---

### FR-09: RFC 9728 OAuth 2.1 and 3-Tier RBAC
- **Description**: When `AUTH_ENABLED=true`, the server must act as an RFC 9728 OAuth 2.1 Protected Resource Server.
- **Metadata Endpoint**: The server must expose authorization metadata at `GET /.well-known/oauth-protected-resource`.
- **Roles**: The system must enforce three permission tiers: Viewer (Level 10), Editor (Level 20), and Admin (Level 30).
- **API Keys**: The system must authenticate requests bearing `cc_` API keys verified against SHA-256 database hashes.

---

### FR-10: 3-Pane Codebase Navigator
- **Description**: The web dashboard must provide an interactive 3-pane architectural navigator.
- **Pane 1 (Files & Modules)**: Virtualized tree hierarchy with search filter and symbol badges.
- **Pane 2 (Symbols & Routes)**: AST declaration list with category chip filters (All, Functions, Classes, Routes).
- **Pane 3 (Code Intelligence & Impact)**: Display incoming callers, outgoing callees, route endpoints, docstrings, and signature code blocks.

---

### FR-11: Dynamic LiteLLM Model Discovery
- **Description**: The system must discover and classify available models from configured LiteLLM proxy endpoints.
- **Categorization**: Models must be automatically sorted into Embedding Models, Vision OCR Models, and Chat Models based on model identifiers and capabilities.
- **Persistence**: Selected model configurations must be persisted to the system metadata database.

---

### FR-12: Diagnostic Observability and Ring Buffer
- **Description**: The system must maintain an in-memory ring buffer of the 500 most recent logging events.
- **REST Interface**: Logs must be accessible via `GET /admin/api/logs` with level filtering (`ALL`, `INFO`, `WARNING`, `ERROR`, `DEBUG`) and keyword search.
- **Traceback Viewer**: The UI must display interactive error tracebacks and allow one-click buffer reset.

---

### FR-13: Unified Ingestion Catalog
- **Description**: The system must provide a unified view of all indexed sources via `what_is_ingested`.
- **Filtering**: Users can filter sources by type (`git`, `monitored_path`, `local_storage`), repository name, path prefix, and file extension.

---

### FR-14: Architectural Decision Records (ADR)
- **Description**: The system must parse and track Architectural Decision Records (MADR format).
- **Operations**: Agents can query, create, and update ADRs via `manage_adr`.

---

### FR-15: Multi-Theme User Interface
- **Description**: The Web Admin Dashboard must provide four visual palettes (Deep Ocean, Midnight Blue, Lavender Haze, Amber Warmth).
- **Responsiveness**: The UI must support desktop and mobile viewport dimensions without horizontal content overflow.
