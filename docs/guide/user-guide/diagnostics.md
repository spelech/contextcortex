# Diagnostics and System Logs

The **Diagnostics & Logs** view provides real-time operational observability into background ingestion workers, Tree-sitter AST parsing tasks, webhook deliveries, and error traces.

---

![Diagnostics and Logs](/assets/desktop_diagnostics.png)

## Real-Time Log Ring Buffer

ContextCortex maintains an in-memory ring buffer of the latest 500 system events:

- **Zero Disk Bloat**: Diagnostic events are held in memory with strict bounding to prevent disk exhaustion.
- **Log Level Filtering**: Filter records by severity:
  - `ALL`: Complete operational stream.
  - `INFO`: Normal indexing and lifecycle updates.
  - `WARNING`: Recoverable warnings (e.g. rate limit thresholds, skipped binary files).
  - `ERROR`: Ingestion errors, failed clones, or unreachable databases.
  - `DEBUG`: Verbose chunking and Tree-sitter parser diagnostics.
- **Keyword Filtering**: Search message content and file paths interactively.
- **Error Traceback Drawer**: Click any `ERROR` log row to open an expanded slide-over drawer showing the full Python stack trace and offending parameters.
- **Clear Buffer**: Click **Clear Logs** to reset the in-memory buffer during testing sessions.

---

## Health Check Probes & MCP Liveness Endpoints

ContextCortex distinguishes process liveness from application readiness for deployment probes in container orchestrators (such as Docker Compose, Kubernetes, Uptime Kuma, and Model Context Gateway):

### 1. Process Liveness Probes (`/health`, `/healthz`)
- **Purpose**: Cheap, low-overhead HTTP process check returning `{"status": "healthy", ...}` (HTTP 200).
- **Scope**: Verifies that the FastAPI process is running and accepting incoming HTTP requests. Process liveness does **not** verify database schema or backend storage readiness.

### 2. Application Readiness Probes (`/ready`, `/readiness`, `/health/ready`, `/healthz/ready`)
- **Purpose**: Deep application readiness signal returning `{"status": "ready", ...}` (HTTP 200) when ready, or `{"status": "not_ready", ...}` (HTTP 503) when required dependencies are unavailable.
- **Dependencies Covered**: Verifies active connectivity to the configured database engine (PostgreSQL or SQLite) and asserts that required relational schema tables (`system_metadata`, `git_repositories`, `indexed_paths`, `indexed_files`, `ast_symbols`, `file_summaries`) exist and are accessible through the selected database pathway used by core operations.
- **Sanitized Response**: Public diagnostic responses are sanitized to ensure database credentials, connection strings, and host secrets are never exposed.
- **Ingestion Note**: Gateway process liveness or readiness verifies schema and API availability, but does not equate to complete background repository ingestion or vector store indexing, which run asynchronously in background workers.

```bash
# 1. Cheap HTTP process liveness probe
curl -s http://localhost:8021/healthz
# Response: {"status":"healthy","protocolVersion":"2026-07-28","server":"contextcortex"}

# 2. Deep application readiness probe
curl -s http://localhost:8021/ready
# Response: {"status":"ready","protocolVersion":"2026-07-28","server":"contextcortex","database":{"status":"ok","type":"sqlite"}}

# 3. Lightweight MCP JSON-RPC ping (bypasses SSE stream/session allocation)
curl -s -X POST http://localhost:8021/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"ping"}'
# Response: {"jsonrpc":"2.0","id":1,"result":{}}

# 4. Detailed index and system statistics
curl -s http://localhost:8021/admin/api/stats
```

---

## Next Steps

- Explore dashboard theme palettes in [Appearance and Theme Customization](/guide/user-guide/themes).
- Review architectural specifications in the [System Architecture](/architecture/) section.
