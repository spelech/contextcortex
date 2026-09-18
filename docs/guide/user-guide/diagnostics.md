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

## Health Check Endpoints

ContextCortex exposes standard health check endpoints for container orchestrators (Docker, Kubernetes, Kuma):

```bash
# Basic liveness probe
curl http://localhost:8021/health
# Response: {"status":"healthy"}

# Detailed diagnostic status
curl http://localhost:8021/admin/api/stats
```

---

## Next Steps

- Explore dashboard theme palettes in [Appearance and Theme Customization](/guide/user-guide/themes).
- Review architectural specifications in the [System Architecture](/architecture/) section.
