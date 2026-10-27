# Admin REST API Reference

The ContextCortex backend exposes REST API endpoints for administration, repository synchronization, codebase navigation, calibrated hybrid search testing, local storage management, settings configuration, and diagnostics.

All administrative routes are prefixed with `/admin/api` unless otherwise noted.

---

## Health, Liveness & OAuth Discovery Endpoints

### 1. Health & Readiness Probe (`/health` & `/healthz`)
- **Method**: `GET`
- **Path**: `/health` or `/healthz`
- **Authentication**: None
- **Response**:
  ```json
  {
    "status": "healthy",
    "service": "ContextCortex",
    "version": "2.19.0",
    "protocolVersion": "2025-06-18"
  }
  ```

### 2. Zero-Allocation MCP JSON-RPC `ping`
- **Method**: `POST`
- **Path**: `/mcp`, `/sse`, or `/messages`
- **Request Body**:
  ```json
  {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "ping"
  }
  ```
- **Response**: Returns `{"jsonrpc": "2.0", "id": 1, "result": {}}` immediately (`200 OK`) via `McpPingMiddleware` without allocating SSE streams or sessions.

### 3. RFC 9728 OAuth 2.1 Protected Resource Metadata
- **Method**: `GET`
- **Path**: `/.well-known/oauth-protected-resource`
- **Authentication**: None
- **Response**: Returns resource URI indicator, authorization server issuers, and supported MCP scopes (`mcp:viewer`, `mcp:editor`, `mcp:admin`).

---

## Repositories, Local Paths & Search API (`app/api/routers/repositories.py`)

### 1. List Registered Repositories
- **Method**: `GET`
- **Path**: `/admin/api/repos`
- **Response**: Array of registered Git repositories, branches, commit SHAs, `keep_shallow` and `auto_sync_enabled` flags, and sync statuses.

### 2. Register Repository
- **Method**: `POST`
- **Path**: `/admin/api/repos`
- **Request Body**:
  ```json
  {
    "name": "my-service",
    "url": "https://github.com/org/my-service.git",
    "branch": "main",
    "provider": "github",
    "keep_shallow": true,
    "auth_token": "ghp_optional_override_token"
  }
  ```

### 3. Toggle Shallow Retention & Auto-Sync
- **Methods**:
  - `PATCH /admin/api/repos/{repo_id}/keep-shallow`
  - `PATCH /admin/api/repos/{repo_id}/auto-sync`
- **Response**: Updates persistent shallow clone retention (`keep_shallow`) or periodic background auto-sync for the repository.

### 4. Synchronize, Stream Progress & Cancel Sync
- **Methods**:
  - `POST /admin/api/repos/{repo_id}/sync`: Triggers background repository synchronization.
  - `GET /admin/api/repos/sync/stream`: Server-Sent Events (SSE) progress stream for active repository syncs.
  - `GET /admin/api/repos/{repo_id}/sync-status`: Current sync phase and progress counters.
  - `POST /admin/api/repos/{repo_id}/cancel-sync`: Cancels an in-flight synchronization run.
  - `DELETE /admin/api/repos/{repo_id}`: Purges repository metadata, shallow clone cache, and associated vector points.

### 5. Monitored Local Paths & Global Indexing
- **Methods**:
  - `GET /admin/api/paths`: Lists monitored local host directories and vaults.
  - `POST /admin/api/paths`: Registers a new monitored host directory (`path`, `category`, `recursive`).
  - `DELETE /admin/api/paths/{path_id}`: Removes a monitored local path.
  - `POST /admin/api/reindex`: Triggers a full re-index across all enabled sources.

### 6. Interactive Calibrated Hybrid Search Tester
- **Method**: `POST`
- **Path**: `/admin/api/search/test`
- **Request Body**:
  ```json
  {
    "query": "GetAuthProviders",
    "doc_type": "code",
    "repo": "mcp-router-code",
    "limit": 10,
    "search_mode": "hybrid",
    "dense_weight": 0.5
  }
  ```
- **Response**: Returns ranked results with fused `score`, decomposed `dense_score` and `sparse_score`, and AST-enriched payload (`symbol`, `signature`, `kind`, `start_line`, `end_line`, `ast_symbol_id`).

---

## Codebase Navigator & Omni-Search API (`app/api/routers/navigator.py` & `files.py`)

### 1. Repository File Tree
- **Method**: `GET`
- **Path**: `/admin/api/navigator/tree?repo={repo_name}`
- **Response**: Hierarchical directory and file tree with per-file AST symbol counts and API route counts.

### 2. File AST Outline
- **Method**: `GET`
- **Path**: `/admin/api/navigator/file-outline?repo={repo_name}&filepath={rel_path}`
- **Response**: AST symbols (`classes`, `functions`, `methods`) and declared REST routes for the file.

### 3. Symbol Impact & Caller/Callee Analysis
- **Method**: `GET`
- **Path**: `/admin/api/navigator/symbol-impact?symbol_id={id}`
- **Response**: Symbol signature, docstring, incoming callers, outgoing callees, imports, and route mappings (aggregating member calls when a container class is selected).

### 4. Universal Omni-Search Command Palette
- **Method**: `GET`
- **Path**: `/admin/api/navigator/omni-search?q={query}&repo={optional_repo}&limit=20`
- **Response**: Fuzzy-ranked matches across repositories, file paths, AST symbols, and API routes with confidence scores.

### 5. Full File Reader & LLM Summarizer (`app/api/routers/files.py`)
- **Methods**:
  - `GET /admin/api/files/read?path={filepath}&repo={repo}&start_line={start}&end_line={end}`: Returns raw or line-bounded file content.
  - `POST /admin/api/files/summarize`: Generates or retrieves a structured LLM executive summary for a file.

---

## Local Storage, Ingestion Catalog & Topology API

### 1. Managed Local Storage & PDF Preview (`app/api/routers/storage.py`)
- **Methods**:
  - `GET /admin/api/storage/tree`: Hierarchical directory tree of `/app/data/storage`.
  - `POST /admin/api/storage/pdf/preview`: Multipart PDF upload returning extracted page text, sample semantic chunks, and AI vision OCR indicators.
  - `POST /admin/api/storage/upload`: Uploads a file to managed storage and triggers immediate AST and vector indexing.
  - `GET /admin/api/storage/file?path={rel_path}`: Reads a stored file.
  - `PUT /admin/api/storage/file`: Replaces an existing stored file and re-indexes it.
  - `DELETE /admin/api/storage/file?path={rel_path}`: Deletes a stored file and purges its vector points and relational records.

### 2. Unified Ingestion Catalog (`app/api/routers/ingestion.py`)
- **Method**: `GET`
- **Path**: `/admin/api/ingestion/catalog?source_type=all&detail_level=summary`
- **Response**: Consolidated inventory across Git repositories, monitored local paths, and managed local storage.

### 3. Dependency Topology Graph (`app/api/routers/graph.py`)
- **Methods**:
  - `GET /admin/api/graph/topology?repo={repo}&view_type=symbols&depth=2`: Returns graph nodes and edges (`CALLS`, `IMPORTS`, `DEFINES`, `ROUTES_TO`).
  - `GET /admin/api/graph/node-details?node_id={id}`: Returns detailed code preview, signature, and neighbor relations for a selected graph node.

---

## Settings, Vector Store & Diagnostics API (`app/api/routers/settings.py`)

### 1. System Statistics & Vector Store Switching
- **Methods**:
  - `GET /admin/api/stats`: Global vector count, AST symbol count, repository totals, and active model specs.
  - `GET /admin/api/vector-store`: Returns active vector store provider (`qdrant`, `pgvector`, `chroma`) and connection settings.
  - `POST /admin/api/vector-store/test`: Tests connectivity and collection readiness for a target vector backend.
  - `POST /admin/api/vector-store/switch`: Dynamically switches the active vector store backend without restarting the server.

### 2. AI Gateway, Embeddings & LiteLLM Model Discovery
- **Methods**:
  - `GET /admin/api/models/discover`: Queries the upstream LiteLLM proxy and returns categorized `embedding_models`, `vision_models`, and `chat_models`.
  - `GET /admin/api/settings/ai-gateway` & `POST /admin/api/settings/ai-gateway`: Reads or updates AI Gateway URL, API key, and model selections.
  - `GET /admin/api/settings/embedding` & `POST /admin/api/settings/embedding`: Reads or updates embedding provider (`local` vs `api`) and model parameters.
  - `GET /admin/api/settings/files` & `POST /admin/api/settings/files`: Reads or updates large-file auto-summarization thresholds and line-read limits.

### 3. Git Host Credentials & Diagnostics Log Buffer
- **Methods**:
  - `GET /admin/api/settings/hosts`, `POST /admin/api/settings/hosts`, `DELETE /admin/api/settings/hosts/{host_id}`: Manages domain-level credentials in the Git Host Credential Vault.
  - `GET /admin/api/logs?level=ERROR&limit=50`: Retrieves recent events from the 500-event in-memory diagnostic ring buffer.
  - `DELETE /admin/api/logs`: Clears the in-memory diagnostic log buffer.

### 4. Multi-Provider Git Webhooks (`app/api/webhooks.py`)
- **Method**: `POST`
- **Path**: `/api/webhooks/git`
- **Response**: Verifies HMAC signatures (`X-Hub-Signature-256`, `X-Gitlab-Token`, `X-Gitea-Signature`) and triggers immediate background synchronization for matching repositories.
