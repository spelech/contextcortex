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

## Health Check & MCP Liveness Endpoints

ContextCortex exposes standard HTTP health probes and a zero-allocation MCP JSON-RPC `ping` handler for container orchestrators and MCP gateways (such as Docker, Kubernetes, Uptime Kuma, and Model Context Gateway):

```bash
# 1. HTTP liveness & readiness probe (/health or /healthz)
curl -s http://localhost:8021/healthz
# Response: {"status":"healthy","service":"ContextCortex","version":"2.19.0","protocolVersion":"2025-06-18"}

# 2. Lightweight MCP JSON-RPC ping (bypasses SSE stream/session allocation)
curl -s -X POST http://localhost:8021/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"ping"}'
# Response: {"jsonrpc":"2.0","id":1,"result":{}}

# 3. Detailed index and system statistics
curl -s http://localhost:8021/admin/api/stats
```

---

## Next Steps

- Explore dashboard theme palettes in [Appearance and Theme Customization](/guide/user-guide/themes).
- Review architectural specifications in the [System Architecture](/architecture/) section.
