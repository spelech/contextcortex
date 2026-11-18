# Non-Functional Requirements

This section specifies the non-functional requirements and quality attributes for ContextCortex.

---

### NFR-01: Modular Architecture Maintainability Limit
- **Requirement**: Source code files in the backend and frontend must maintain a strict limit of fewer than 500 lines of code (LOC).
- **Rationale**: Keeps components focused, enhances readability, prevents architectural degradation, and facilitates automated agent refactoring.

---

### NFR-02: Query Response Latency
- **Requirement**: Symbol lookup (`find_symbol`) and file outline (`read_file(..., outline_only=True)`) requests must return within 50 milliseconds for codebases containing up to 100,000 indexed symbols.
- **Hybrid Vector Queries**: Dense and sparse hybrid search requests must return within 350 milliseconds under standard CPU execution.

---

### NFR-03: Storage Footprint and Ephemeral Ingestion
- **Requirement**: Remote Git repositories cloned during synchronization must not persist on the host filesystem after AST extraction and embedding generation are complete.
- **Disk Usage**: Relational metadata and vector storage overhead must remain under 15% of the raw indexed source code size.

---

### NFR-04: Security and Path Sanitization
- **Requirement**: All file storage paths must be sanitized against directory traversal attacks.
- **Rule**: Requests containing parent path tokens (`..`), leading root slashes (`/`), or null bytes (`\0`) must be rejected with HTTP 400 Bad Request.
- **Authentication**: When `AUTH_ENABLED=true`, unauthenticated calls to protected routes must be rejected with HTTP 401 Unauthorized within 10 milliseconds.

---

### NFR-05: Concurrency and Thread Safety
- **Requirement**: In SQLite mode, database operations must use Write-Ahead Logging (WAL) and a 15000ms busy timeout to prevent `database is locked` operational errors under concurrent indexing and search loads.
- **PostgreSQL Mode**: Connection pooling via `psycopg3` must handle up to 20 concurrent connections with automatic reconnect logic.

---

### NFR-06: Resource Boundaries and Batch Capping
- **Requirement**: Embedding generation and background indexing must not starve host CPU, memory, or upstream gateway rate limits.
- **Local Thread Cap**: `EMBEDDING_NUM_THREADS` (default `min(2, N_cpu)`) caps ONNX Runtime CPU worker threads per local FastEmbed model (`EMBEDDING_PROVIDER=local` and local sparse BM25 tokenization). It has no effect on remote dense embeddings when `EMBEDDING_PROVIDER=api`.
- **Cross-File Batching & API Concurrency**: Embedding requests batch chunks across files according to `EMBEDDING_BATCH_SIZE` (default `32` for `local`, `128` for `api`, clamped to `256` per API request) and `EMBEDDING_MAX_TOKENS_PER_REQUEST` (default `100000`). When `EMBEDDING_PROVIDER=api`, up to `EMBEDDING_API_CONCURRENCY` (default `4`) batches execute in parallel with automatic HTTP `429` `Retry-After` backoff, AIMD concurrency scaling, and optional `EMBEDDING_TPM_LIMIT` (default `0` / disabled) token-bucket pacing.

---

### NFR-07: Cross-Device UI Responsiveness
- **Requirement**: The web administration interface must adapt seamlessly across screen widths from 360px (mobile) to 2560px (desktop).
- **Layout Inspector**: The UI must pass automated Playwright layout inspector audits ensuring zero horizontal window overflow across all tested breakpoints.

---

### NFR-08: Documentation Clarity and Structure
- **Requirement**: All user guides, architectural specifications, and requirement documents must follow clear, concise technical writing rules.
- **Constraints**:
  - Keep procedural instructions under 20 words per sentence and descriptive statements under 25 words where practical.
  - Use active voice and imperative command verbs for instructions.
  - Avoid contractions and ambiguous terminology.
  - Use structured headings, tables, and numbered lists for multi-step procedures.
