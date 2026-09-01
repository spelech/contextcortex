# Developer Documentation: ContextCortex (v2.12.0)

This document provides instructions for developing, testing, configuring, and running ContextCortex locally.

---

## 🛠️ Prerequisites

- **Python 3.11+**
- **Node.js 20+** & **npm** (for the React 19 frontend)
- **Git** (for shallow repository cloning)
- **Vector Database**: Qdrant (local/Docker or embedded) or ChromaDB (embedded/disk or remote)
- **FastEmbed** (included in `requirements.txt` for in-process ONNX CPU embeddings)

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

5. **Start Vector Database (Optional - defaults to embedded Qdrant/Chroma):**
   ```bash
   docker run -d --name qdrant -p 6333:6333 -p 6334:6334 \
       -v $(pwd)/data/qdrant_storage:/qdrant/storage \
       qdrant/qdrant:latest
   ```

6. **Set Environment Variables (Optional):**
   ```bash
   export VECTOR_STORE_PROVIDER="qdrant" # "qdrant" or "chroma"
   export COLLECTION_NAME="knowledge_rag_v1"
   export EMBEDDING_PROVIDER="local" # "local" (FastEmbed) or "api" (LiteLLM)
   export EMBEDDING_MODEL="BAAI/bge-small-en-v1.5"
   export SPARSE_MODEL="Qdrant/bm25"
   export EMBEDDING_NUM_THREADS=2 # CPU thread cap for ONNX (defaults to min(2, system_cpus))
   export EMBEDDING_BATCH_SIZE=32 # Batch size for tokenization (defaults to 32)
   export GITHUB_TOKEN="ghp_your_token" # Optional: For higher rate limits & private repos
   ```

7. **Run the server:**
   ```bash
   python main.py
   ```
   The server starts on port `3000`, initializes SQLite tables (`index_cache.db`), configures vector storage (Qdrant/ChromaDB), mounts `/admin/` static files, and binds both `/sse` and `/mcp` FastMCP transport endpoints.

---

## 🧪 Running Automated Test Suites

### Backend Tests (Python Pytest & Coverage)
```bash
# Run all backend unit and integration tests (277 tests)
pytest -v

# Run backend tests with code coverage report (88% coverage baseline)
pytest -v --cov=app --cov-report=term-missing
```

### Frontend Tests (React / TypeScript)
```bash
cd frontend

# Run unit and component tests via Vitest (82 tests)
npm test

# Run component tests with code coverage (87% line coverage)
npm run test:coverage

# Run end-to-end user journey tests via Playwright (26 user journeys)
npx playwright test
```

### Software Requirements Specification (SRS) Generator
```bash
# Regenerate and validate REQUIREMENTS.md against live test suite
python3 scripts/generate_requirements.py
pytest -v tests/backend/test_requirements_sync.py
```

---

## ⚙️ Configuration Variables

| Variable | Description | Default |
| :--- | :--- | :--- |
| `DATABASE_URL` | SQLAlchemy connection string (e.g. `postgresql+psycopg://...` or `sqlite:///...`) | `sqlite:////app/data/index_cache.db` |
| `LOCAL_STORAGE_PATH` | Storage directory for managed local storage file uploads | `/app/data/storage` |
| `AUTH_ENABLED` | Enable MCP 2026-07-28 OAuth 2.1 & API Key RBAC | `false` |
| `VECTOR_STORE_PROVIDER` | Vector database backend (`pgvector`, `qdrant`, or `chroma`) | `qdrant` |
| `VECTOR_STORE_MODE` | Vector store mode (`embedded` or `remote`) | `embedded` |
| `COLLECTION_NAME` | Vector collection name | `knowledge_rag_v1` |
| `QDRANT_URL` | URL to the remote Qdrant vector database | `http://localhost:6333` |
| `QDRANT_STORAGE_PATH` | Storage directory for embedded Qdrant | `/app/data/qdrant_storage` |
| `CHROMA_STORAGE_PATH` | Storage directory for embedded ChromaDB | `/app/data/chroma_db` |
| `EMBEDDING_PROVIDER` | Embedding engine (`local` for in-process ONNX, `api` for LiteLLM/OpenAI) | `local` |
| `EMBEDDING_MODEL` | FastEmbed dense model name | `BAAI/bge-small-en-v1.5` |
| `SPARSE_MODEL` | FastEmbed sparse BM25 model name | `Qdrant/bm25` |
| `GITHUB_TOKEN` | Optional GitHub Personal Access Token for rate limits & private repos | `None` |
| `VAULT_PATH` | Default path to the markdown documentation directory | `/docs` |
| `CACHE_DB_PATH` | Path to persistent SQLite cache database | `/app/data/index_cache.db` |
| `CHUNK_SIZE` | Maximum character length per chunk | `1500` |
| `CHUNK_OVERLAP` | Character overlap between consecutive chunks | `200` |

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
│       ├── vector_store/  # pgvector, Qdrant, and ChromaDB pluggable vector store implementations
│       ├── navigator.py   # High-performance 3-pane codebase tree, outline & impact intelligence
│       ├── local_storage.py# Safe path resolution, disk file persistence, and tree inspection
│       ├── git_manager.py # Ephemeral shallow git clone, token masking, permalinks
│       ├── embeddings.py  # FastEmbed dense (384d) & sparse BM25 multi-vector engine
│       ├── search.py      # Hybrid search & Reciprocal Rank Fusion (RRF) reranker
│       ├── poller.py      # Background scheduled repo SHA poller daemon
│       ├── adr.py         # MADR / Nygard format ADR ingestion and lifecycle
│       ├── architecture.py# Codebase entry point, language distribution synthesis
│       └── logger.py      # In-memory 500-event ring buffer diagnostic logger
├── tests/                 # Backend pytest test suite (430+ tests, 88% coverage)
│   ├── backend/           # Unit and integration test modules
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
├── requirements.txt       # Python dependencies
├── Dockerfile             # Container definition with Python 3.11 & Git
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

### Available MCP Tools (14 Tools):
- `search_code(query="JWT authentication handler", repo="backend-api")` [Role: `viewer`]
- `search_docs(query="caddy reverse proxy configuration")` [Role: `viewer`]
- `find_symbol(name="extract_symbols_and_chunks", exact=true)` [Role: `viewer`]
- `trace_path(target="authenticate_user", repo="backend-api")` [Role: `viewer`]
- `find_routes(repo="backend-api")` [Role: `viewer`]
- `find_api_callers(target="/api/v1/auth/login")` [Role: `viewer`]
- `get_file_outline(filepath="app/services/search.py")` [Role: `viewer`]
- `list_repositories()` [Role: `viewer`]
- `sync_repository(repo="backend-api")` [Role: `editor`]
- `index_status()` [Role: `viewer`]
- `get_architecture(repo="backend-api")` [Role: `viewer`]
- `manage_adr(action="list", repo="backend-api")` [Role: `editor`]
- `manage_local_file(action="upload", file_path="notes/spec.md", content="# Spec")` [Role: `editor` for mutations, `viewer` for read]
- `what_is_ingested(source_type="all", detail_level="summary")` [Role: `viewer`]

### Available MCP Resources:
- `knowledge://catalog/summary`

### Available MCP Prompts:
- `search_infrastructure_docs(topic="docker-compose network topology")`
- `find_implementation_symbol(symbol="execute_hybrid_search")`

---

## 🌐 REST API Specifications & RBAC Matrix

### Role-Based Access Control (RBAC) Matrix
| Resource / Operation | HTTP Endpoint | MCP Tool | Required Role |
| :--- | :--- | :--- | :---: |
| List / Search API Keys | `GET /admin/api/auth/keys` | - | `Role.ADMIN` |
| Create / Revoke API Keys | `POST/DELETE /admin/api/auth/keys` | - | `Role.ADMIN` |
| Upload Local Storage File | `POST /admin/api/storage/upload` | `manage_local_file (upload)` | `Role.EDITOR` |
| Replace Local Storage File | `PUT /admin/api/storage/file` | `manage_local_file (replace)` | `Role.EDITOR` |
| Delete Local Storage File | `DELETE /admin/api/storage/file` | `manage_local_file (delete)` | `Role.EDITOR` |
| Read Local Storage File | `GET /admin/api/storage/file` | `manage_local_file (read)` | `Role.VIEWER` |
| Browse Storage Directory Tree | `GET /admin/api/storage/tree` | - | `Role.VIEWER` |
| Query Ingestion Catalog | `GET /admin/api/ingestion/catalog` | `what_is_ingested` | `Role.VIEWER` |
| Repository Navigator Tree | `GET /admin/api/navigator/tree` | - | `Role.VIEWER` |
| File Symbol Outline | `GET /admin/api/navigator/file-outline` | - | `Role.VIEWER` |
| Symbol Impact Intelligence | `GET /admin/api/navigator/symbol-impact` | - | `Role.VIEWER` |
| Sync Git Repository | `POST /admin/api/repositories/{id}/sync`| `sync_repository` | `Role.EDITOR` |
| Manage ADRs | - | `manage_adr` (create/update) | `Role.EDITOR` |
| Code & Document Searches | `POST /admin/api/search` | `search_code`, `search_docs` | `Role.VIEWER` |

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

