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
    "version": "2.20.0",
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
- **Required Role**: `Role.VIEWER`
- **Response**: Array of registered Git repositories, branches, commit SHAs, `keep_shallow` and `auto_sync` flags, `retain_commits_count`, `file_count`, and sync statuses.

### 2. Register Repository (`POST /admin/api/repos`)
- **Method**: `POST`
- **Path**: `/admin/api/repos`
- **Required Role**: `Role.ADMIN`
- **Request Fields (`RepoConfig`)**:
  - `name` (string, required): Unique repository identifier used across search, navigator, and MCP tools.
  - `url` (string, required): Remote HTTPS or SSH Git clone URL.
  - `branch` (string, optional, default `"main"`): Target Git branch to track and index.
  - `pat` or `auth_token` (string, optional): Personal access token or repository token override (`pat` is accepted as an alias for `auth_token`).
  - `provider` (string, optional, default `"github"`): Git provider hint (`"github"`, `"gitlab"`, `"gitea"`, `"bitbucket"`, or `"generic"`). Auto-detected from `url` when omitted.
  - `auth_user` (string, optional): Optional HTTP basic auth username when required by the Git host.
  - `auto_sync` (boolean, optional, default `true`): Enable periodic background SHA polling for this repository.
  - `keep_shallow` (boolean, optional, default `false`): Retain the shallow clone on disk under `PERSISTENT_REPOS_DIR` for instant full-file reads and fast incremental fetches.
  - `retain_commits_count` (integer, optional, default `20`): Number of recent commit metadata records retained in `git_commits` (`0` disables commit history storage).
  - `webhook_secret` (string, optional): Per-repository HMAC secret for `/api/webhooks/git`.
- **Scripted `curl` Example**:
  ```bash
  curl -X POST http://localhost:3000/admin/api/repos \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer cc_admin_your_key" \
    -d '{
      "name": "my-service",
      "url": "https://github.com/org/my-service.git",
      "branch": "main",
      "pat": "ghp_optional_override_token",
      "provider": "github",
      "keep_shallow": true,
      "retain_commits_count": 20
    }'
  ```
- **Response (`200 OK`)**:
  ```json
  {
    "status": "success",
    "id": 1
  }
  ```
  Registration immediately spawns a background synchronization thread for the new `id`.

### 3. Toggle Shallow Retention, Auto-Sync & Commit Retention
- **Methods**:
  - `PATCH /admin/api/repos/{repo_id}/keep-shallow` (`{"keep_shallow": true}`)
  - `PATCH /admin/api/repos/{repo_id}/auto-sync` (`{"auto_sync": true}`)
  - `PATCH /admin/api/repos/{repo_id}/retain-commits` (`{"retain_commits_count": 20}`)
- **Required Role**: `Role.ADMIN`
- **Response**: Updates persistent shallow clone retention (`keep_shallow`), periodic background auto-sync (`auto_sync`), or stored commit count (`retain_commits_count`) for the repository.

### 4. Synchronize, Stream Progress & Cancel Sync
- **Methods**:
  - `POST /admin/api/repos/{repo_id}/sync` (or `POST /admin/api/repos/sync/{repo_id}`): Triggers background repository synchronization (`Role.EDITOR`).
  - `GET /admin/api/repos/sync/stream`: Server-Sent Events (SSE) progress stream for active repository syncs (`Role.VIEWER`).
  - `GET /admin/api/repos/sync-status`: Snapshot of all active repository sync jobs (`Role.VIEWER`).
  - `GET /admin/api/repos/{repo_id}/sync-status`: Current sync phase, file/chunk counters, embedding throughput (`chunks_per_sec`), and HTTP `429` wait telemetry (`rate_limit_429_count`, `rate_limit_wait_seconds`) for a single repository (`Role.VIEWER`).
  - `POST /admin/api/repos/{repo_id}/cancel-sync`: Cancels an in-flight synchronization run (`Role.EDITOR`).

### 5. Delete Repository (`DELETE /admin/api/repos/{repo_id}`)
- **Method**: `DELETE`
- **Path**: `/admin/api/repos/{repo_id}`
- **Required Role**: `Role.ADMIN`
- **Scripted `curl` Example**:
  ```bash
  curl -X DELETE http://localhost:3000/admin/api/repos/1 \
    -H "Authorization: Bearer cc_admin_your_key"
  ```
- **Response (`200 OK`)**:
  ```json
  {
    "status": "success",
    "name": "my-service",
    "deleted": "my-service"
  }
  ```
- **What `DELETE /admin/api/repos/{repo_id}` Removes**:
  1. The repository registration row in `git_repositories`.
  2. All relational rows where `repo = <name>` across `indexed_files`, `file_summaries`, `ast_symbols`, `ast_relationships`, `api_routes`, `api_client_calls`, and `git_commits`.
  3. All dense and sparse vector points for `<name>` in the active vector store (`pgvector` or `qdrant`).
  4. The retained shallow clone directory on disk under `PERSISTENT_REPOS_DIR` (if `keep_shallow` was enabled).

### 6. Monitored Local Paths & Global Indexing (`GET` / `POST` / `DELETE /admin/api/paths`)
- **List Monitored Paths (`GET /admin/api/paths`)**:
  - **Required Role**: `Role.VIEWER`
  - **Response**: Array of rows from `indexed_paths` (`id`, `path`, `type`, `recursive`, `category`, `repo`, `enabled`).
- **Register Monitored Path (`POST /admin/api/paths`)**:
  - **Required Role**: `Role.ADMIN`
  - **Request Fields (`LocalPathConfig`)**:
    - `path` (string, required): Existing absolute directory or file path on the host/container filesystem (validated against path traversal and null bytes).
    - `type` (string, optional, default `"directory"`): Path entry type (`"directory"` or `"file"`).
    - `recursive` (boolean, optional, default `true`): Recursively traverse subdirectories during indexing.
    - `category` (string, optional, default `null`): Optional classification tag attached to indexed chunks.
    - `repo` (string, optional, default `"local"`): Logical repository/source label assigned to files indexed from this path.
  - **Scripted `curl` Example**:
    ```bash
    curl -X POST http://localhost:3000/admin/api/paths \
      -H "Content-Type: application/json" \
      -H "Authorization: Bearer cc_admin_your_key" \
      -d '{
        "path": "/docs/architecture",
        "type": "directory",
        "recursive": true,
        "category": "runbooks",
        "repo": "local"
      }'
    ```
  - **Response (`200 OK`)**:
    ```json
    {
      "status": "success",
      "id": 2,
      "path": "/docs/architecture"
    }
    ```
    Registration immediately triggers a background `run_full_indexing()` pass.
- **Delete Monitored Path (`DELETE /admin/api/paths/{path_id}`)**:
  - **Required Role**: `Role.ADMIN`
  - **Scripted `curl` Example**:
    ```bash
    curl -X DELETE http://localhost:3000/admin/api/paths/2 \
      -H "Authorization: Bearer cc_admin_your_key"
    ```
  - **Response (`200 OK`)**:
    ```json
    {
      "status": "success",
      "path": "/docs/architecture",
      "deleted": "/docs/architecture"
    }
    ```
  - **What `DELETE /admin/api/paths/{path_id}` Removes**:
    1. The monitored path entry in `indexed_paths`.
    2. All relational rows matching the removed path (or its subpath prefix `<path>/%`, plus `repo`-scoped rows when no other registered path or Git repository shares that `repo` label) across `indexed_files`, `file_summaries`, `ast_symbols`, `ast_relationships`, `api_routes`, and `api_client_calls`.
    3. All vector points matching the removed path (and unshared `repo` label) in the active vector store (`pgvector` or `qdrant`). Files on the underlying host disk are never deleted.
- **Trigger Global Re-Index (`POST /admin/api/reindex` or `POST /admin/api/sync`)**:
  - **Required Role**: `Role.EDITOR`
  - **Query Parameter**: `force` (boolean, optional, default `false`).
  - **Response**: Dispatches a background indexing run across all enabled sources (returns `409 Conflict` if an indexing run is already active).

### 7. Interactive Calibrated Hybrid Search Tester
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
  - `GET /admin/api/vector-store`: Returns active vector store provider (`qdrant` or `pgvector`) and connection settings.
  - `POST /admin/api/vector-store/test`: Tests connectivity and collection readiness for a target vector backend.
  - `POST /admin/api/vector-store/switch`: Dynamically switches the active vector store backend without restarting the server.

### 2. AI Gateway, Embeddings & Model Discovery
- **Methods**:
  - `GET /admin/api/models/discover`: Queries the upstream OpenAI-compatible AI Gateway (`/v1/models`) and returns categorized `embedding_models`, `vision_models`, and `chat_models`.
  - `GET /admin/api/settings/ai-gateway` & `POST /admin/api/settings/ai-gateway`: Reads or updates AI Gateway URL (`OPENAI_API_URL`), API key (`OPENAI_API_KEY`), and model selections.
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
