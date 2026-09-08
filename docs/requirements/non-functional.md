# Non-Functional Requirements

This section specifies the non-functional requirements and quality attributes for ContextCortex.

---

### NFR-01: Modular Architecture Maintainability Limit
- **Requirement**: Source code files in the backend and frontend must maintain a strict limit of fewer than 500 lines of code (LOC).
- **Rationale**: Keeps components focused, enhances readability, prevents architectural degradation, and facilitates automated agent refactoring.

---

### NFR-02: Query Response Latency
- **Requirement**: Symbol lookup (`find_symbol`) and file outline (`get_file_outline`) requests must return within 50 milliseconds for codebases containing up to 100,000 indexed symbols.
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
- **Requirement**: In SQLite mode, database operations must use Write-Ahead Logging (WAL) and a 5000ms busy timeout to prevent `database is locked` operational errors under concurrent indexing and search loads.
- **PostgreSQL Mode**: Connection pooling via `psycopg3` must handle up to 20 concurrent connections with automatic reconnect logic.

---

### NFR-06: Resource Boundaries and Thread Capping
- **Requirement**: On-device FastEmbed ONNX embedding generation must not starve host CPU resources.
- **Thread Cap**: The ONNX runtime worker thread count must default to $\min(2, N_{\text{cpu}})$, with user overrides available via `EMBEDDING_NUM_THREADS`.

---

### NFR-07: Cross-Device UI Responsiveness
- **Requirement**: The web administration interface must adapt seamlessly across screen widths from 360px (mobile) to 2560px (desktop).
- **Layout Inspector**: The UI must pass automated Playwright layout inspector audits ensuring zero horizontal window overflow across all tested breakpoints.

---

### NFR-08: Documentation Clarity (ASD-STE100 Compliance)
- **Requirement**: All user guides, architectural specifications, and requirement documents must comply with the rules of ASD-STE100 Simplified Technical English (Issue 9).
- **Constraints**:
  - Maximum sentence length: 20 words for procedural instructions, 25 words for descriptions.
  - Active voice must be used. Passive voice is permitted only when the agent is unknown.
  - Contractions are forbidden.
  - Vertical lists must be used for complex step enumerations.
