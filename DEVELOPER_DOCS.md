# Developer Documentation: ContextCortex (v2.28.8) <!-- x-release-please-version -->

This document provides instructions for developing, testing, configuring, and running ContextCortex locally.

---

## 🗄️ Relational Database Selection, Schema Migration & Rollback

ContextCortex supports unified relational database selection across **SQLite** (default local embedded storage) and **PostgreSQL** (enterprise local deployment profiles).

### Database Engine Selection
- **SQLite (Default)**: Used when `DATABASE_URL` is unset or starts with `sqlite:///`. Relational metadata and index caches are stored at `/app/data/index_cache.db` (configurable via `CACHE_DB_PATH`).
- **PostgreSQL**: Selected by setting `DATABASE_URL` to a valid PostgreSQL connection string (e.g., `postgresql+psycopg://user:password@postgres:5432/contextcortex`).
  - When PostgreSQL is selected, all relational access across repositories, settings, credentials, indexing, file summaries, AST symbols, API routes, relationships, search, ADRs, and file deletion routes through the unified `PostgresConnectionAdapter`.
  - **No Fallback SQLite Files**: When PostgreSQL is selected, the application operates exclusively against PostgreSQL and will never create or query an unrelated fallback SQLite file.

### Schema Migration
1. **Automated Schema Initialization**: Schema tables and initial seed data (custom prompts, system metadata, vector store configuration) are initialized on startup via `init_db()`.
2. **Canonical SQLAlchemy Core Schema**: Table definitions are specified in `app/services/database/schema.py`. Running `init_db()` calls `metadata.create_all(bind=engine)` to idempotently create missing tables across SQLite and PostgreSQL.
3. **Column Migration Checks**: `ensure_git_repositories_columns()` and `ensure_file_summaries_columns()` verify table columns on startup (e.g. `keep_shallow`, `summary_text`) using `information_schema` on PostgreSQL or `PRAGMA table_info` on SQLite.
4. **pgvector Extension**: When initializing PostgreSQL, `init_db()` executes `CREATE EXTENSION IF NOT EXISTS vector;` to enable vector operations for pgvector storage.

### Database Rollback Strategy
If you need to roll back or switch storage engines between PostgreSQL and SQLite:
1. **Switch Connection URL**: Set `DATABASE_URL` to the desired storage target (e.g., unset `DATABASE_URL` or set `DATABASE_URL="sqlite:////app/data/index_cache.db"` to revert to SQLite).
2. **Initialize Target Schema**: Start the application (`python main.py`) or call `init_db()`. The database engine factory initializes target schema tables idempotently without modifying or destroying data in the previously active database.
3. **Re-index Content**: Trigger re-indexing (`run_full_indexing()` or via the UI/API) to populate repository files, symbols, and summaries into the target relational database.

---

## 🛠️ Prerequisites

- **Python 3.11+**
- **Node.js 20+** & **npm** (for the React 19 frontend)
- **Git** (for shallow repository cloning)
- **Vector Database**: PostgreSQL 16 (`pgvector`) or Qdrant (embedded disk or remote server)
- **OpenAI-Compatible Gateway**: Internal LLM gateway, LiteLLM, vLLM, Ollama, or OpenAI endpoint

---

## 💻 Local Setup

### Option A: Automated One-Command Setup (Recommended)

**Linux / macOS (Bash):**
```bash
git clone git@github.com:spelech/contextcortex.git
cd contextcortex
./setup.sh
```

**Windows (PowerShell):**
```powershell
git clone git@github.com:spelech/contextcortex.git
cd contextcortex
.\setup.ps1
```

### Option B: Manual Setup

1. **Clone the repository:**
   ```bash
   git clone git@github.com:spelech/contextcortex.git
   cd contextcortex
   ```

2. **Create a virtual environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install Python dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Install Frontend dependencies & build bundle:**
   ```bash
   cd frontend
   npm install
   npm run build
   cd ..
   ```

5. **Start Vector Database (Optional - defaults to `pgvector` when `DATABASE_URL` is PostgreSQL, or embedded Qdrant otherwise):**
   ```bash
   docker run -d --name qdrant -p 6333:6333 -p 6334:6334 \
       -v $(pwd)/data/qdrant_storage:/qdrant/storage \
       qdrant/qdrant:latest
   ```

6. **Set Environment Variables (Optional):**
   ```bash
   export VECTOR_STORE_PROVIDER="pgvector" # "pgvector" or "qdrant"
   export VECTOR_STORE_COLLECTION="knowledge_rag_v1" # Alias: COLLECTION_NAME
   export OPENAI_API_URL="http://litellm:4000/v1" # OpenAI-compatible gateway endpoint
   export OPENAI_API_KEY="sk-your-key" # Gateway API key / Bearer token
   export EMBEDDING_PROVIDER="local" # "local" (FastEmbed ONNX) or "api" (OpenAI-compatible gateway)
   export EMBEDDING_NUM_THREADS=2 # CPU thread cap for local FastEmbed ONNX only (defaults to min(2, system_cpus); no effect when EMBEDDING_PROVIDER=api)
   export EMBEDDING_BATCH_SIZE=32 # Texts per embedding call (defaults to 32 for local, 128 for api, max 256 per API request)
   export EMBEDDING_API_CONCURRENCY=4 # Max concurrent in-flight API embedding requests when EMBEDDING_PROVIDER=api
   export LLM_EXTRA_HEADERS='{"X-User-Agent":"contextcortex"}' # Optional JSON extra headers for LLM gateway requests
   export EXTRA_CA_CERTS_DIR="/certs" # Optional directory of private CA certificates (*.crt)
   export GITHUB_TOKEN="ghp_your_token" # Optional: For higher rate limits & private repos
   ```

7. **Run the server:**
   ```bash
   python main.py
   ```
   The server starts on port `3000`, initializes database tables (`PostgreSQL` or `index_cache.db`), configures vector storage (`pgvector` or `Qdrant`), mounts `/admin/` static files, and binds both `/sse` and `/mcp` FastMCP transport endpoints. Models (Embedding, Chat, Vision OCR) can then be discovered and selected directly in **Settings → AI & Model Gateway**.

---

## 🧪 Running Automated Test Suites

### Backend Tests (Python Pytest & Coverage)
```bash
# Run all backend unit and integration tests (698 tests)
pytest -v

# Run backend tests with code coverage report (89%+ coverage baseline)
pytest -v --cov=app --cov-report=term-missing
```

### Frontend Tests (React / TypeScript)
```bash
cd frontend

# Run unit and component tests via Vitest (303 tests across 32 test files)
npm test

# Run component tests with code coverage
npm run test:coverage

# Run end-to-end user journey tests via Playwright (50 tests)
npx playwright test
```

### Software Requirements Specification (SRS) Generator
```bash
# Regenerate and validate REQUIREMENTS.md against live test suite
python3 scripts/generate_requirements.py
pytest -v tests/backend/test_requirements_sync.py
```

### MCP & Agent Benchmarks
See [`benchmarks/README.md`](benchmarks/README.md) and [`docs/reference/benchmarks.md`](docs/reference/benchmarks.md) for isolated `:18021` schema, latency, and OpenCode A/B runs:
```bash
./benchmarks/setup_and_run_server.sh start
python3 benchmarks/measure_tool_schemas.py
python3 benchmarks/run_micro_bench.py --runs 3
python3 -u benchmarks/run_benchmark.py --tasks-file benchmarks/examples/custom_tasks.example.json
./benchmarks/setup_and_run_server.sh stop
```

### VitePress Documentation Site
```bash
# Start local documentation dev server
npm run docs:dev

# Build production static documentation site
npm run docs:build

# Preview built production documentation site
npm run docs:preview
```

---

## ⚙️ Configuration Variables

| Variable | Description | Default |
| :--- | :--- | :--- |
| `HOST` | Listen address (`0.0.0.0` in Docker, `localhost` in Windows portable bundle) | `0.0.0.0` |
| `PORT` | HTTP server port for FastAPI, Admin UI, and MCP endpoints | `3000` |
| `LOG_LEVEL` | Application log verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`) | `INFO` |
| `DATABASE_URL` | SQLAlchemy connection string (e.g. `postgresql+psycopg://...` or `sqlite:///...`) | `sqlite:////app/data/index_cache.db` |
| `DATA_DIR` | Root data directory for persistent application state | `/app/data` |
| `CACHE_DB_PATH` | Path to persistent SQLite cache database | `/app/data/index_cache.db` |
| `LOCAL_STORAGE_PATH` | Storage directory for managed local storage file uploads | `/app/data/storage` |
| `VAULT_PATH` | Default path to the Markdown documentation directory | `/docs` |
| `TMP_REPOS_DIR` | Ephemeral workspace directory for shallow Git clones during sync | `/tmp/contextcortex_repos` |
| `PERSISTENT_REPOS_DIR` | Storage directory for retained shallow Git clones (`keep_shallow`) | `/app/data/repos` |
| `GIT_CLONE_TIMEOUT_SECONDS` | Timeout in seconds for `git clone` / `git fetch` operations | `300` |
| `VECTOR_STORE_PROVIDER` | Vector database backend (`pgvector` or `qdrant`) | `pgvector` (Postgres) / `qdrant` (SQLite) |
| `VECTOR_STORE_MODE` | Vector store mode (`embedded` or `remote`) | `embedded` |
| `VECTOR_STORE_STORAGE_PATH` | Storage directory for embedded Qdrant (`QDRANT_STORAGE_PATH` alias) | `/app/data/qdrant_storage` |
| `VECTOR_STORE_COLLECTION` | Vector collection name (`COLLECTION_NAME` alias) | `knowledge_rag_v1` |
| `QDRANT_URL` | URL to the remote Qdrant vector database | `http://localhost:6333` |
| `HYBRID_DENSE_WEIGHT` | Default dense semantic weight (`0.0` to `1.0`) for hybrid search fusion | `0.5` |
| `OPENAI_API_URL` | OpenAI-compatible gateway base URL passed to the OpenAI SDK | `http://litellm:4000/v1` |
| `OPENAI_API_KEY` | API key for the OpenAI-compatible gateway | `dummy` |
| `LLM_EXTRA_HEADERS` | JSON object of extra HTTP headers sent on every gateway request | `None` |
| `EMBEDDING_PROVIDER` | Dense embedding execution backend (`local` FastEmbed ONNX or `api` gateway) | `local` |
| `EMBEDDING_MODEL` | Active dense embedding model identifier | `BAAI/bge-small-en-v1.5` (`local`) / `text-embedding-3-small` (`api`) |
| `SPARSE_MODEL` | Local FastEmbed sparse lexical model for BM25 token weights | `Qdrant/bm25` |
| `EMBEDDING_ALLOW_FALLBACK` | Allow fallback to local dense model if API embedding initialization fails | `false` |
| `EMBEDDING_FALLBACK_DENSE_MODEL` | Local dense model used when `EMBEDDING_ALLOW_FALLBACK=true` | `BAAI/bge-small-en-v1.5` |
| `EMBEDDING_NUM_THREADS` | ONNX Runtime CPU threads per local FastEmbed model (`EMBEDDING_PROVIDER=local` only; no effect when `EMBEDDING_PROVIDER=api`) | `min(2, system_cpus)` |
| `EMBEDDING_BATCH_SIZE` | Texts per embedding call across files (clamped to `256` per API request) | `32` (`local`) / `128` (`api`) |
| `EMBEDDING_API_CONCURRENCY` | Maximum concurrent in-flight API embedding requests during indexing (`EMBEDDING_PROVIDER=api`) | `4` |
| `EMBEDDING_MAX_TOKENS_PER_REQUEST` | Estimated token budget cap per API embedding request batch | `100000` |
| `EMBEDDING_TPM_LIMIT` | Client-side tokens-per-minute pacing limit (`0` = disabled, reactive `429` handling only) | `0` |
| `VISION_OCR_MODEL` | Multimodal vision model for scanned PDF / diagram OCR fallback | `gpt-4o-mini` |
| `CHAT_MODEL` | Default chat completion model for large-file executive summarization | `gpt-4o-mini` |
| `EXTRA_CA_CERTS_DIR` | Directory of private CA certificates (`*.crt`) trusted at container start | `/certs` |
| `MCP_ENABLE_WRITE_TOOLS` | Expose the state-mutating `manage` MCP tool (`sync_repo`, `upload`, `replace`, `delete`) | `false` |
| `CODE_MODE_ENABLED` | Enable the sandboxed `execute_script` Code Mode MCP tool | `true` |
| `CODE_MODE_TIMEOUT_SECONDS` | Maximum wall-clock execution time in seconds for a single `execute_script` call | `10.0` |
| `CODE_MODE_MAX_TOOL_CALLS` | Maximum inner `tools.*()` invocations allowed per `execute_script` run | `50` |
| `CODE_MODE_MAX_MEMORY_MB` | Maximum QuickJS heap memory in megabytes per `execute_script` sandbox | `64` |
| `AUTH_ENABLED` | Enable MCP OAuth 2.1 (RFC 9728) & `cc_` API Key RBAC | `false` |
| `AUTH_OIDC_ISSUER` | OpenID Connect Identity Provider issuer URL | `None` |
| `AUTH_JWKS_URI` | Custom JSON Web Key Set URL override for JWT verification | `None` |
| `AUTH_RESOURCE_INDICATOR` | RFC 8707 / RFC 9728 OAuth 2.1 Resource Indicator URI | `https://contextcortex.local` |
| `ADMIN_INITIAL_KEY` | Initial Admin API key seeded on first startup | `None` |
| `GLOBAL_WEBHOOK_SECRET` | Fallback HMAC secret for `/api/webhooks/git` when a repo has no per-repo secret | `None` |
| `GITHUB_TOKEN` | Optional GitHub Personal Access Token for rate limits & private repos | `None` |
| `GITLAB_TOKEN` | Optional GitLab Personal Access Token | `None` |
| `GITEA_TOKEN` | Optional Gitea / Forgejo Access Token | `None` |
| `BITBUCKET_TOKEN` | Optional Bitbucket App Password / Token | `None` |

---

## 📁 Modular Project Structure

```
contextcortex/
├── main.py                # FastAPI entry point, lifespan manager & FastMCP route mounting
├── app/                   # Modular architecture (all files < 450 LOC)
│   ├── api/               # FastAPI REST routers
│   │   ├── routers/       # Dedicated subrouters (repositories, settings, navigator, auth, storage, ingestion)
│   │   ├── routes.py      # Main router aggregator and health checks
│   │   └── webhooks.py    # Multi-provider webhook endpoint and HMAC validation
│   ├── mcp/               # FastMCP 2.0 dual-transport server
│   │   ├── handlers/      # Modular tool handlers (search, symbol, repo, route, architecture, storage)
│   │   ├── mcp_server.py  # FastMCP server lifecycle & session registry
│   │   └── tools.py       # Tool registry and handler dispatcher
│   ├── models/            # Pydantic schema validation models
│   │   └── schemas.py     # Request/response schemas for APIs and MCP
│   └── services/          # Modular business logic services
│       ├── auth/          # RBAC engine, JWT validator, API key lifecycle, models
│       ├── chunking/      # Tree-sitter loaders, token chunkers, AST/route extractors
│       ├── database/      # Relational schema, engine pool, credential vault, ADRs, sync configs
│       ├── indexing/      # Git/local syncers, file processor, state notifications
│       ├── topology/      # Graph topology builder, node details, BFS helpers
│       ├── vector_store/  # pgvector and Qdrant pluggable vector store implementations
│       ├── navigator.py   # High-performance codebase tree, outline & impact intelligence
│       ├── omni_search.py # Unified fuzzy command palette search for files, repos, and symbols
│       ├── file_reader.py # Safe full-file source and markdown content resolution from disk
│       ├── local_storage.py# Safe path resolution, disk file persistence, and tree inspection
│       ├── git_manager.py # Shallow git clone (ephemeral & persistent), token masking, permalinks
│       ├── embeddings.py  # OpenAI-compatible dense & sparse BM25 multi-vector engine
│       ├── llm_client.py  # Shared OpenAI-compatible gateway config, URL builder & header validator
│       ├── litellm_service.py # Model discovery, API embeddings & gateway health checks
│       ├── summarizer.py  # Large-file executive LLM summarization service
│       ├── pdf_extractor.py # PDF text extraction with Vision OCR fallback
│       ├── search.py      # Hybrid search & Reciprocal Rank Fusion (RRF) reranker
│       ├── poller.py      # Background scheduled repo SHA poller daemon
│       ├── adr.py         # MADR / Nygard format ADR ingestion and lifecycle
│       ├── architecture.py# Codebase entry point, language distribution synthesis
│       └── logger.py      # In-memory 500-event ring buffer diagnostic logger
├── tests/                 # Backend pytest test suite (698 tests, 89%+ coverage)
│   ├── backend/           # Unit and integration test modules
│   ├── test_llm_client.py            # Gateway URL resolution, extra headers & real-DB fallback tests
│   ├── test_litellm_service.py       # LiteLLM model discovery & embedding header propagation tests
│   ├── test_docker_entrypoint.py     # Runtime CA certificate bootstrap & fail-closed tests
│   ├── test_docker_orchestration.py  # Dockerfile, overlay, and Compose contract verification tests
│   ├── test_navigator_router.py      # REST navigator endpoints tests
│   ├── test_navigator_service.py     # Tree, outline, and impact service tests
│   ├── test_local_storage_service.py # Path security and local disk storage tests
│   ├── test_local_storage_indexing.py# Real-time incremental vector indexing tests
│   ├── test_mcp_storage_tools.py     # manage_local_file and what_is_ingested tests
│   ├── test_storage_api_routes.py    # REST storage and ingestion endpoint tests
│   ├── test_auth_service.py          # Authentication and API key service tests
│   ├── test_poller.py                # Background poller tests
│   └── test_webhooks.py              # Multi-provider webhook tests
├── frontend/              # Web Admin Dashboard (React 19, TypeScript, Vite)
│   ├── src/               # React components and modular sub-components
│   │   ├── components/    # Sub-component trees (git/, settings/, topology/, navigator/)
│   │   │   └── navigator/ # NavigatorToolbar, NavigatorTree, NavigatorOutline, NavigatorInspector
│   │   ├── CodeNavigator.tsx          # 3-Pane Codebase Navigator main orchestrator
│   │   ├── LocalStorageManager.tsx    # Managed storage file explorer and upload modal
│   │   ├── IngestionCatalogViewer.tsx # Unified multi-source ingestion explorer
│   │   ├── styles/        # Modular CSS stylesheets (base.css, components.css, navigator.css)
│   │   └── tests/         # Vitest component unit tests
│   ├── e2e/               # Playwright E2E test specs (26 user journeys)
│   └── dist/              # Compiled production distribution assets
├── certs/                 # Private CA certificates (*.crt) for build-time and runtime trust
├── requirements.txt       # Python dependencies
├── Dockerfile             # Multi-stage container definition with mirror & CA support
├── Dockerfile.overlay     # Fast CA-trust overlay on pre-built ContextCortex image
├── docker-entrypoint.sh   # Runtime private CA certificate bootstrap entrypoint
├── docker-compose.enterprise.yml # Compose override for verified local image & custom CA mounts
├── ARCHITECTURE.md        # Deep architectural design specification
├── DEVELOPER_DOCS.md      # Local developer setup and test guide
└── docs/
    ├── REQUIREMENTS.md    # Pointer to root Software Requirements Specification
    └── TEST_COVERAGE.md   # Full test coverage report and metrics breakdown
```

---

## 📡 Connecting MCP Clients

Connect any MCP client supporting **Server-Sent Events (SSE)** or **Streamable HTTP**:

### 1. Server-Sent Events (SSE)
- **SSE Stream Endpoint**: `http://localhost:3000/sse`
- **Message Exchange Endpoint**: `http://localhost:3000/messages/`

Example configuration (`claude_desktop_config.json` / Cursor / Antigravity):
```json
{
  "mcpServers": {
    "contextcortex-sse": {
      "url": "http://localhost:3000/sse",
      "headers": {
        "Authorization": "Bearer cc_live_your_api_key_here"
      }
    }
  }
}
```

### 2. Streamable HTTP
- **Streamable HTTP Endpoint**: `http://localhost:3000/mcp`

Example configuration:
```json
{
  "mcpServers": {
    "contextcortex-http": {
      "url": "http://localhost:3000/mcp",
      "headers": {
        "Authorization": "Bearer cc_live_your_api_key_here"
      }
    }
  }
}
```

### Available MCP Tools (10 Default Tools + Optional `manage` Write Tool):
- `diagnose_issue(issue_text="Traceback (most recent call last): ...", repo="backend-api")` [Role: `viewer`] — First tool to call on bug reports, stack traces, or regressions; correlates candidate symbols, recent commits, `call_chain`, and `working_path_comparison`.
- `search(query="JWT authentication handler", repo="backend-api", content_type="code", mode="hybrid", dense_weight=0.5)` [Role: `viewer`] — Calibrated hybrid semantic + BM25 search across code and documentation (`content_type`: `"all"`, `"code"`, or `"docs"`).
- `grep_code(pattern="enforce_tool_permission", repo="backend-api", path_glob="*.py")` [Role: `viewer`] — Exact or regex source code search with context lines.
- `find_symbol(symbol="extract_symbols_and_chunks", exact=true)` [Role: `viewer`] — Locate function, class, or method definitions via the AST index.
- `trace_path(symbol="authenticate_user", repo="backend-api", direction="both", depth=1)` [Role: `viewer`] — Multi-hop caller, callee, import, and inheritance graph traversal (`depth` `1` to `5`).
- `find_routes(repo="backend-api", direction="both")` [Role: `viewer`] — Discover declared HTTP/REST API routes and outbound client HTTP calls.
- `read_file(path="app/services/search.py", repo="backend-api", start_line=1, end_line=120, outline_only=false, summarize=false)` [Role: `viewer`] — Read line-bounded source files, AST symbol outlines (`outline_only=True`), or LLM executive summaries (`summarize=True`).
- `list_repositories(include_status=false, include_catalog=false, recent_commits=0)` [Role: `viewer`] — List indexed repositories alongside optional sync status, ingestion catalog counts, and recent commits.
- `get_architecture(repo="backend-api", include_adrs=true)` [Role: `viewer`] — Synthesize repository entry points, language distribution, directory hotspots, and Architectural Decision Records (ADRs).
- `execute_script(code="const h = await tools.help('search'); return h;")` [Role: `viewer`, enabled when `CODE_MODE_ENABLED=true`] — Execute sandboxed JavaScript in QuickJS with `await tools.<name>(args)` and `await tools.help('<name>')` to chain multiple read-only MCP calls in one round-trip.
- `manage(action="sync_repo", repo="backend-api")` [Role: `editor` for `sync_repo`, `upload`, `replace`, `delete`; `viewer` for `read`, `preview`; registered only when `MCP_ENABLE_WRITE_TOOLS=true`] — Unified administrative tool for repository sync and managed local storage mutations.

### Available MCP Resources & Resource Templates:
- `knowledge://catalog/summary` — Global ingestion catalog and vector index summary (`application/json`).
- `contextcortex://code-mode/sdk.d.ts` — TypeScript ambient declarations (`declare namespace tools`) and return-shape contracts for the `execute_script` sandbox (`text/plain`).
- `knowledge://repo/{repo}/summary` — Repository metadata, branch, commit SHA, and file/symbol counts.
- `knowledge://repo/{repo}/architecture` — Synthesized repository architecture overview.
- `knowledge://repo/{repo}/files/{page}` — Paginated list of indexed files (`100` files per page).
- `knowledge://repo/{repo}/routes/{page}` — Paginated list of discovered API routes (`100` routes per page).
- `knowledge://repo/{repo}/adrs` — Architectural Decision Records for the specified repository.

### Available MCP Prompts:
- `search_infrastructure_docs(topic="docker-compose network topology")`
- `find_implementation_symbol(symbol="execute_hybrid_search", repo="backend-api")`
- `onboard_repository(repo="backend-api")`
- `triage_error(issue_text="KeyError: 'user_id'", repo="backend-api")`
- `investigate_change_impact(symbol="authenticate_user", repo="backend-api")`

---

## 🌐 REST API Specifications & RBAC Matrix

### Role-Based Access Control (RBAC) Matrix
| Resource / Operation | HTTP Endpoint | MCP Tool | Required Role |
| :--- | :--- | :--- | :---: |
| List / Search API Keys | `GET /admin/api/auth/keys` | - | `Role.ADMIN` |
| Create / Revoke API Keys | `POST/DELETE /admin/api/auth/keys` | - | `Role.ADMIN` |
| Add / Delete Git Repository | `POST/DELETE /admin/api/repos` | - | `Role.ADMIN` |
| Add / Delete Monitored Path | `POST/DELETE /admin/api/paths` | - | `Role.ADMIN` |
| Upload Local Storage File | `POST /admin/api/storage/upload` | `manage (action="upload")` | `Role.EDITOR` |
| Replace Local Storage File | `PUT /admin/api/storage/file` | `manage (action="replace")` | `Role.EDITOR` |
| Delete Local Storage File | `DELETE /admin/api/storage/file` | `manage (action="delete")` | `Role.EDITOR` |
| Read Local Storage File | `GET /admin/api/storage/file` | `manage (action="read")` | `Role.VIEWER` |
| Browse Storage Directory Tree | `GET /admin/api/storage/tree` | - | `Role.VIEWER` |
| Query Ingestion Catalog | `GET /admin/api/ingestion/catalog` | `list_repositories(include_catalog=True)` | `Role.VIEWER` |
| Repository Navigator Tree | `GET /admin/api/navigator/tree` | - | `Role.VIEWER` |
| File Symbol Outline | `GET /admin/api/navigator/file-outline` | `read_file(outline_only=True)` | `Role.VIEWER` |
| Symbol Impact Intelligence | `GET /admin/api/navigator/symbol-impact` | `trace_path` | `Role.VIEWER` |
| Sync Git Repository | `POST /admin/api/repos/{id}/sync` | `manage (action="sync_repo")` | `Role.EDITOR` |
| Read Architecture & ADRs | - | `get_architecture` | `Role.VIEWER` |
| Code, Doc & Issue Searches | `POST /admin/api/search/test` | `search`, `grep_code`, `diagnose_issue` | `Role.VIEWER` |
| Sandboxed Multi-Tool Script | - | `execute_script` | `Role.VIEWER` |

### Codebase Navigator Component Hierarchy
The frontend architecture implements a modular 3-pane layout under `frontend/src/components/navigator/`:
- **`CodeNavigator.tsx`**: Primary container handling repository selection state, file selection state, symbol selection state, and density modes (`Compact`, `Balanced`, `Spacious`).
  - **`NavigatorToolbar.tsx`**: Top bar with repository dropdown selector, total file/symbol metric badges, layout density toggles, and reindexing status.
  - **`NavigatorTree.tsx`**: Left pane rendering hierarchical directory/file tree with symbol and route count badges, debounced search filtering, expand/collapse all controls, and keyboard selection.
  - **`NavigatorOutline.tsx`**: Middle pane rendering file-scoped AST symbols, category chips (`All`, `Functions`, `Classes`, `Routes`), signature badges, and line number indicators.
  - **`NavigatorInspector.tsx`**: Right pane rendering symbol details, 4-metric summary grid (callers, callees, imports, scope), API route mapping cards, signature code blocks, docstrings, interactive relationship click-through cards, and copy permalink actions.

### REST Payload Schemas

#### 1. Codebase Navigator Tree (`GET /admin/api/navigator/tree`)
- **Query Parameters**: `repo` (optional, string, defaults to `__all__`).
- **Response** (`200 OK`):
  ```json
  {
    "repo": "__all__",
    "total_files": 42,
    "total_symbols": 380,
    "tree": [
      {
        "id": "dir:app",
        "name": "app",
        "is_dir": true,
        "path": "app",
        "symbol_count": 210,
        "route_count": 18,
        "children": [
          {
            "id": "file:app/api/routes.py",
            "name": "routes.py",
            "is_dir": false,
            "path": "app/api/routes.py",
            "language": "python",
            "symbol_count": 12,
            "route_count": 4
          }
        ]
      }
    ]
  }
  ```

#### 2. File Outline (`GET /admin/api/navigator/file-outline`)
- **Query Parameters**: `filepath` (required, string), `repo` (optional, string).
- **Response** (`200 OK`):
  ```json
  {
    "repo": "contextcortex-core",
    "filepath": "app/api/routers/chat.py",
    "language": "python",
    "symbols": [
      {
        "id": 101,
        "name": "chat_completion_endpoint",
        "full_symbol": "app.api.routers.chat.chat_completion_endpoint",
        "kind": "function",
        "start_line": 45,
        "end_line": 85,
        "signature": "async def chat_completion_endpoint(request: ChatCompletionRequest) -> ChatCompletionResponse:",
        "route": {
          "http_method": "POST",
          "path_pattern": "/v1/chat/completions",
          "framework": "FastAPI"
        }
      }
    ]
  }
  ```

#### 3. Symbol Impact (`GET /admin/api/navigator/symbol-impact`)
- **Query Parameters**: `symbol_id` (optional, integer) or `name` + `filepath` (strings).
- **Response** (`200 OK`):
  ```json
  {
    "symbol": {
      "id": 101,
      "name": "chat_completion_endpoint",
      "full_symbol": "app.api.routers.chat.chat_completion_endpoint",
      "kind": "function",
      "filepath": "app/api/routers/chat.py",
      "start_line": 45,
      "end_line": 85,
      "signature": "async def chat_completion_endpoint(request: ChatCompletionRequest) -> ChatCompletionResponse:",
      "docstring": "Processes OpenAI-compatible chat completion requests.",
      "language": "python",
      "repo": "contextcortex-core"
    },
    "route": {
      "http_method": "POST",
      "path_pattern": "/v1/chat/completions",
      "framework": "FastAPI"
    },
    "callers": [
      {
        "id": 501,
        "source_symbol_id": 301,
        "source_filepath": "tests/e2e/test_chat.py",
        "source_symbol": "test_chat_completions_e2e",
        "target_symbol": "chat_completion_endpoint",
        "relationship_type": "CALLS",
        "line_number": 28
      }
    ],
    "callees": [],
    "imports": []
  }
  ```

#### 4. File Upload (`POST /admin/api/storage/upload`)
- **Multipart Form**: `file` (binary), `path` (relative target path), optional `repo` (default `"local_storage"`), optional `category`.
- **JSON Payload**:
  ```json
  {
    "path": "rfcs/caching-v2.md",
    "content": "# RFC: Caching Architecture v2\n\nDesign notes...",
    "repo": "local_storage",
    "category": "rfcs"
  }
  ```
- **Response** (`200 OK`):
  ```json
  {
    "status": "success",
    "rel_path": "rfcs/caching-v2.md",
    "repo": "local_storage",
    "category": "rfcs",
    "size_bytes": 1240,
    "chunks_indexed": 3
  }
  ```

#### 5. File Replace (`PUT /admin/api/storage/file`)
- **JSON Payload**:
  ```json
  {
    "path": "rfcs/caching-v2.md",
    "content": "# Updated RFC: Caching Architecture v2\n\nRevised design...",
    "repo": "local_storage",
    "category": "rfcs"
  }
  ```
- **Response** (`200 OK`):
  ```json
  {
    "status": "success",
    "rel_path": "rfcs/caching-v2.md",
    "repo": "local_storage",
    "size_bytes": 1410,
    "chunks_indexed": 4
  }
  ```

#### 6. Ingestion Catalog Query (`GET /admin/api/ingestion/catalog`)
- **Query Parameters**: `source_type` (`all`|`git`|`monitored_path`|`local_storage`), `repo_name`, `path_prefix`, `file_extension`, `detail_level` (`summary`|`detailed`).
- **Response** (`200 OK`):
  ```json
  {
    "source_type": "all",
    "detail_level": "summary",
    "git_repositories": [
      {
        "id": 1,
        "name": "contextcortex",
        "url": "https://github.com/spelech/contextcortex",
        "branch": "main",
        "commit_sha": "a7c8950...",
        "provider": "github",
        "status": "synced",
        "file_count": 42
      }
    ],
    "monitored_paths": [],
    "local_storage": {
      "root_path": "/app/data/storage",
      "file_count": 5,
      "tree": {
        "root": "/app/data/storage",
        "current_folder": "",
        "directories": [{"name": "rfcs", "rel_path": "rfcs", "abs_path": "/app/data/storage/rfcs"}],
        "files": [{"name": "spec.md", "rel_path": "rfcs/spec.md", "abs_path": "/app/data/storage/rfcs/spec.md", "size_bytes": 1024, "mtime": 1724800000.0}]
      }
    },
    "files": []
  }
  ```

