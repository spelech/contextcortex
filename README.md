# ContextCortex (v2.12.0)


[![Build and Publish Docker Image](https://github.com/spelech/contextcortex/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/spelech/contextcortex/actions/workflows/docker-publish.yml)
[![Docker Image](https://img.shields.io/badge/ghcr.io-spelech%2Fcontextcortex-blue?logo=docker)](https://github.com/spelech/contextcortex/pkgs/container/contextcortex)

A high-performance, multi-repo Model Context Protocol (MCP) server providing **syntax-aware Code RAG**, **Hybrid Retrieval (Dense + BM25)**, **Tree-sitter AST chunking**, **Pluggable Dual-Engine Architecture (PostgreSQL 16 + pgvector & SQLite)**, **MCP 2026-07-28 OAuth 2.1 & 3-Tier RBAC**, and **Universal Git Provider indexing** with an integrated Web Admin Dashboard (ContextCortex) and real-time Diagnostic Observability.
<details>
<summary><b>🖼️ View Dashboard Components</b></summary>

| Overview | Git Repositories |
|:---:|:---:|
| ![Overview](docs/assets/desktop_overview.png) | ![Git Repos](docs/assets/desktop_git-repos.png) |
| **Search & Inspector** | **Local Paths** |
| ![Search](docs/assets/desktop_search-inspector.png) | ![Local Paths](docs/assets/desktop_local-paths.png) |
| **Settings** | **Diagnostics & Logs** |
| ![Settings](docs/assets/desktop_settings.png) | ![Diagnostics](docs/assets/desktop_diagnostics.png) |

</details>

<details open>
<summary><b>🎨 Multi-Theme Appearance (4 Polished Palettes)</b></summary>

| **Deep Ocean** *(Dark Default)* | **Midnight Blue** *(Dark Space)* |
|:---:|:---:|
| ![Deep Ocean](docs/assets/theme_deep_ocean.png) | ![Midnight Blue](docs/assets/theme_midnight_blue.png) |
| *Petrol spruce `#07181b` with vibrant cyan `#0891b2` & mint* | *Obsidian navy `#0a0f1d` with royal blue `#3b82f6` & teal* |
| **Lavender Haze** *(Light Purple)* | **Amber Warmth** *(Light Sandstone)* |
|:---:|:---:|
| ![Lavender Haze](docs/assets/theme_lavender_haze.png) | ![Amber Warmth](docs/assets/theme_amber_warmth.png) |
| *Lilac canvas `#f5f3ff` with purple `#7c3aed` & fuchsia* | *Sandstone `#fdf8f4` with terracotta `#ea580c` & amber* |

</details>


---

## 🌟 Key Features

- **Pluggable Dual-Engine Architecture**:
  - **PostgreSQL 16 + pgvector Profile**: Containerized production deployment with native `vector(384)` HNSW cosine distance indexing (`vector_cosine_ops`), `JSONB` metadata payload queries, and robust connection pooling (`psycopg3`).
  - **SQLite Profile**: Zero-configuration, zero-dependency embedded disk mode with automatic WAL journaling, 5000ms busy timeout, and resilient relational caching.
- **SQLAlchemy 2.0 Core Unified Schema**: Single source of truth relational schema (`metadata`) shared seamlessly between SQLite and PostgreSQL, with startup connection retry loops (`wait_for_db`) and automatic metadata seeding.
- **MCP 2026-07-28 OAuth 2.1 & RBAC Security Engine**:
  - **RFC 9728 Protected Resource Metadata**: Standard discovery endpoint at `/.well-known/oauth-protected-resource` exposing resource indicators, authorization server issuers, and MCP scopes.
  - **JWT & OIDC Discovery**: Validates RS256/ES256 signed bearer tokens with automatic JWKS key discovery and cached key rotation.
  - **Database-Backed API Keys**: Cryptographically secure `cc_...` API keys with SHA-256 hash verification, expiration timestamps, and one-click revocation.
  - **3-Tier RBAC Hierarchy**: `admin` (Level 30 / `mcp:admin`), `editor` (Level 20 / `mcp:editor`), and `viewer` (Level 10 / `mcp:viewer`).
  - **Zero-Friction Local Dev Bypass**: Runs in unrestricted admin mode when `AUTH_ENABLED=false` for local developer velocity.
- **FastMCP 2.0 Native Architecture**: Built on the official Model Context Protocol Python SDK 2.0.0+ (`FastMCP`), supporting modern decorator patterns, typed schemas, dynamic catalog resources, and custom agent prompts.
- **Dual MCP Transports**:
  - **Server-Sent Events (SSE)**: Full streaming events at `/sse` with POST message routing at `/messages/`.
  - **Streamable HTTP**: Bidirectional JSON-RPC transport endpoint at `/mcp`.
- **Multi-Vector Database Backends**:
  - **pgvector**: PostgreSQL 16 vector extension with HNSW cosine search.
  - **Qdrant**: High-scale vector engine supporting dense + sparse BM25 multi-vectors with Reciprocal Rank Fusion (RRF) in both embedded disk and remote server modes.
  - **ChromaDB**: Lightweight, zero-dependency embedded disk or remote vector store with automatic fallback.
  - **Dynamic Backend Switching**: Test and switch vector backends live from the Settings UI or REST API without server restarts.
- **Universal Git Provider Support**:
  - Ingest repositories from **any source where Git lives**: **GitHub**, **GitLab (Cloud, Enterprise & Self-Hosted)**, **Gitea & Forgejo**, **Bitbucket (Cloud & Server)**, and **Generic Git HTTP/HTTPS**.
  - **Provider-Aware Permalinks**: Automatically generates exact deep-links for code results (`/blob/`, `/-/blob/`, `/src/branch/`, `/src/commit/`, `/src/#lines-`).
  - **Custom Git Host Credential Vault**: Register per-host tokens and authentication types for private internal domains (e.g. `gitlab.company.internal` or `http://git.lan:3000`).
- **AST-Aware Code Chunking (Tree-sitter)**: Understands syntax structures across Python, TypeScript/JavaScript, Go, Rust, C#, C++, Java, Ruby, PHP, and more. Chunks along class, method, and function boundaries with exact line numbers and symbol names.
- **Ephemeral Repository Ingestion**: Authenticated shallow clones (`--depth 1`) extract AST symbols and hybrid vectors and **immediately remove the cloned repository from disk** to conserve storage.
- **Multi-Tier Git Authentication Hierarchy**:
  1. Per-repository override token & optional username.
  2. Domain-level Custom Git Host Vault (`git_host_credentials`).
  3. Global provider tokens (`GITHUB_TOKEN`, `GITLAB_TOKEN`, `GITEA_TOKEN` in DB or Settings UI).
  4. Environment variable fallback.
- **Managed Local Storage Option & Real-Time Incremental Indexing**:
  - Direct file upload, replace, read, and delete operations within a managed directory (`LOCAL_STORAGE_PATH` / `/app/data/storage`).
  - Real-time incremental AST extraction, semantic chunking, embedding generation, and vector store upserts with zero delay.
  - Strict path sanitization preventing directory traversal attacks (`..`, leading slashes, null bytes).
  - Immediate vector point and relational metadata purging upon file deletion.
- **Unified Ingestion Catalog (`what_is_ingested`)**:
  - Comprehensive inspection of all ingested Git repositories, monitored local directory vaults, and uploaded local storage files.
  - Granular multi-dimensional filtering by `source_type` (`all`, `git`, `monitored_path`, `local_storage`), `repo_name`, `path_prefix`, and `file_extension`.
  - Flexible granularity (`summary` for totals and status; `detailed` for hierarchical file trees).
- **Fast Deterministic Symbol Lookup**: Built-in symbol table (`ast_symbols`) powers instantaneous symbol searches (`find_symbol`) and file outlines (`get_file_outline`) without token bloat.
- **Diagnostic Logging & Observability**: In-memory ring buffer (500 events) capturing server warnings, errors, indexing lifecycle events, and expandable stack traces with a REST API (`/admin/api/logs`).
- **Multi-Theme Engine & Modern Tabbed Web Dashboard (`/admin/`)**:
  - **Appearance & Theme Settings**: Instant zero-latency switching between 4 distinct dark and light themes (**Deep Ocean**, **Midnight Blue**, **Lavender Haze**, and **Amber Warmth**) with live palette swatches and browser persistence.
  - **Overview**: Real-time stats, vector counts, AST symbols, model specs, topic tag cloud, and manual full reindexing trigger.
  - **Git Repositories**: Register repos across GitHub, GitLab, Gitea, Bitbucket, or Generic Git, trigger shallow clone syncs, inspect commit SHAs, and manage sources.
  - **Local Paths**: Monitor local workspaces and notes vaults with recursive directory scanning and filesystem browser modal.
  - **Local Storage**: Managed file explorer, direct file upload modal with folder categorization, and file preview/replacement.
  - **Ingestion Catalog**: Unified multi-source explorer with source type filters, repository lookup, and file listings.
  - **Search & Inspector**: Interactive live hybrid search tester with RRF score previews, target type toggle (Code vs Docs), and syntax highlighted results.
  - **Settings**: Vector Database manager (pgvector, Qdrant, & ChromaDB switcher & connection tester), multi-provider token cards, GitHub rate limit monitor, and interactive Custom Git Host Credential Vault table/modal.
  - **Diagnostics & Logs**: Real-time log viewer with level filtering (ALL, INFO, WARNING, ERROR, DEBUG), keyword search, traceback modal/drawer, and buffer clearing.

---

## 🛠️ MCP Tools, Resources & Prompts

### Tools & RBAC Permissions
| Tool | Required Role | Parameters | Description |
| :--- | :---: | :--- | :--- |
| `search_code` | `viewer` | `query` (str), `repo` (str, opt), `language` (str, opt), `limit` (int, default 5) | Hybrid semantic + BM25 code search. Returns code blocks with line ranges & clickable git permalinks. |
| `search_docs` | `viewer` | `query` (str), `repo` (str, opt), `category` (str, opt), `tag` (str, opt), `limit` (int, default 5) | Hybrid search across markdown documentation, system architecture, and runbooks. |
| `find_symbol` | `viewer` | `name` (str), `repo` (str, opt), `exact` (bool, default True), `limit` (int, default 10) | Instant exact or prefix AST symbol lookup (functions, classes, structs, interfaces). |
| `get_file_outline` | `viewer` | `filepath` (str), `repo` (str, opt) | Returns the AST structure (classes, methods, signatures, lines) without full file token costs. |
| `list_repositories` | `viewer` | *None* | Lists all registered Git repositories and local paths with commit SHAs and indexing status. |
| `sync_repository` | `editor` | `repo` (str, opt) | Triggers background shallow clone sync for a specific repository or all sources. |
| `index_status` | `viewer` | *None* | Returns vector counts, collection status, embedding models, and GitHub rate limits. |
| `get_architecture` | `viewer` | `repo` (str, opt) | Synthesizes codebase entry points, language breakdown, core directories, and architectural overview. |
| `manage_adr` | `editor` | `action` (str: `list`\|`get`\|`create`\|`update`), `repo` (str, opt), `title` (str, opt), `decision` (str, opt), `status` (str, opt) | Query, create, or update Architectural Decision Records (MADR / Nygard format). |
| `get_code_routes` | `viewer` | `repo` (str, opt), `framework` (str, opt), `http_method` (str, opt) | Returns API endpoint route definitions and HTTP client invocations across backend frameworks. |
| `trace_call_path` | `viewer` | `target` (str), `repo` (str, opt), `direction` (str, default `downstream`), `depth` (int, default 3) | Traces AST symbol calls, imports, inheritance, and cross-repo API client-to-route connections via BFS. |
| `manage_local_file` | `editor` / `viewer` | `action` (str: `upload`\|`replace`\|`delete`\|`read`), `file_path` (str), `content` (str, opt), `repo` (str, opt), `category` (str, opt) | Manage files in ContextCortex local storage: upload, replace, read, or delete files with immediate vector indexing. |
| `what_is_ingested` | `viewer` | `source_type` (str, opt), `repo_name` (str, opt), `path_prefix` (str, opt), `file_extension` (str, opt), `detail_level` (str, opt) | Inspect all ingested Git repositories, monitored local paths, and uploaded local storage files with optional filtering. |

### Resources
| Resource URI | MIME Type | Description |
| :--- | :--- | :--- |
| `knowledge://catalog/summary` | `text/markdown` | Dynamic catalog of all indexed repositories, document distributions, and AST symbol totals. |


### Prompts
| Prompt Name | Arguments | Description |
| :--- | :--- | :--- |
| `search_infrastructure_docs` | `topic` (str) | Guided agent workflow to retrieve system architecture, container port mappings, and reverse proxy configs. |
| `find_implementation_symbol` | `symbol` (str), `repo` (str, opt) | Guided agent workflow to locate symbol definitions, class signatures, and implementations. |

---

## ⚙️ Environment Variables

| Variable | Description | Default |
| :--- | :--- | :--- |
| `DATABASE_URL` | SQLAlchemy connection string (e.g. `postgresql+psycopg://user:pass@host:5432/db` or `sqlite:////app/data/index_cache.db`) | `sqlite:////app/data/index_cache.db` |
| `POSTGRES_DB` | PostgreSQL database name (Docker Compose) | `contextcortex` |
| `POSTGRES_USER` | PostgreSQL username (Docker Compose) | `contextcortex` |
| `POSTGRES_PASSWORD` | PostgreSQL password (Docker Compose) | `cortexsecret` |
| `POSTGRES_PORT` | PostgreSQL host port mapping | `5432` |
| `LOCAL_STORAGE_PATH` | Managed local storage directory for direct file uploads & real-time incremental indexing | `/app/data/storage` |
| `AUTH_ENABLED` | Enable MCP 2026-07-28 OAuth 2.1 & API Key RBAC | `false` |
| `AUTH_OIDC_ISSUER` | OpenID Connect Identity Provider Issuer URL (e.g. `https://auth.company.com/realms/master`) | `None` |
| `AUTH_JWKS_URI` | Custom JWKS URI override for JWT verification | `None` |
| `AUTH_RESOURCE_INDICATOR` | RFC 8707 / RFC 9728 Resource Indicator for ContextCortex | `https://contextcortex.local` |
| `ADMIN_INITIAL_KEY` | Initial admin API key or secret token for container bootstrapping | `None` |
| `VECTOR_STORE_PROVIDER` | Vector database backend (`pgvector`, `qdrant`, or `chroma`) | `qdrant` |
| `VECTOR_STORE_MODE` | Vector store mode (`embedded` or `remote`) | `embedded` |
| `COLLECTION_NAME` | Vector collection name | `knowledge_rag_v1` |
| `QDRANT_URL` | URL to remote Qdrant vector database (if mode is `remote`) | `http://localhost:6333` |
| `QDRANT_STORAGE_PATH` | Embedded Qdrant disk directory | `/app/data/qdrant_storage` |
| `CHROMA_STORAGE_PATH` | Embedded ChromaDB disk directory | `/app/data/chroma_db` |
| `EMBEDDING_PROVIDER` | Embedding engine (`local` for in-process ONNX, `api` for LiteLLM/OpenAI) | `local` |
| `EMBEDDING_MODEL` | FastEmbed dense model name | `BAAI/bge-small-en-v1.5` |
| `SPARSE_MODEL` | FastEmbed sparse BM25 model name | `Qdrant/bm25` |
| `GITHUB_TOKEN` | Optional GitHub Personal Access Token for higher rate limits & private repos | `None` |
| `VAULT_PATH` | Default path to the markdown documentation directory | `/docs` |
| `CACHE_DB_PATH` | Path to persistent SQLite cache database | `/app/data/index_cache.db` |
| `CHUNK_SIZE` | Maximum character length per chunk | `1500` |
| `CHUNK_OVERLAP` | Character overlap between consecutive chunks | `200` |

---

## 🚀 Running via Docker Compose (Recommended)

ContextCortex provides a production-ready multi-container configuration with **PostgreSQL 16 + pgvector**:

```bash
# 1. Clone the repository
git clone git@github.com:spelech/contextcortex.git
cd contextcortex

# 2. Copy and customize environment variables (optional)
cp .env.example .env

# 3. Launch PostgreSQL 16 + pgvector and ContextCortex
docker compose up -d
```

### `docker-compose.yml` Architecture:
```yaml
version: '3.8'

services:
  postgres:
    image: pgvector/pgvector:pg16
    container_name: contextcortex-postgres
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${POSTGRES_DB:-contextcortex}
      POSTGRES_USER: ${POSTGRES_USER:-contextcortex}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-cortexsecret}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "${POSTGRES_PORT:-5432}:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $$POSTGRES_USER -d $$POSTGRES_DB"]
      interval: 5s
      timeout: 5s
      retries: 5

  contextcortex:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: contextcortex-app
    restart: unless-stopped
    depends_on:
      postgres:
        condition: service_healthy
    ports:
      - "${PORT:-3000}:3000"
    environment:
      DATABASE_URL: postgresql+psycopg://${POSTGRES_USER:-contextcortex}:${POSTGRES_PASSWORD:-cortexsecret}@postgres:5432/${POSTGRES_DB:-contextcortex}
      AUTH_ENABLED: ${AUTH_ENABLED:-false}
      AUTH_OIDC_ISSUER: ${AUTH_OIDC_ISSUER:-}
      AUTH_JWKS_URI: ${AUTH_JWKS_URI:-}
      AUTH_RESOURCE_INDICATOR: ${AUTH_RESOURCE_INDICATOR:-https://contextcortex.local}
      ADMIN_INITIAL_KEY: ${ADMIN_INITIAL_KEY:-}
      LOCAL_STORAGE_PATH: ${LOCAL_STORAGE_PATH:-/app/data/storage}
    volumes:
      - repo_cache:/app/data

volumes:
  postgres_data:
  repo_cache:
```

---

## 💻 Running Locally (Bare-Metal)

ContextCortex can be run directly on Linux, macOS, or Windows without Docker dependencies. By default, it operates with **zero external services required** by leveraging embedded Qdrant/ChromaDB, local SQLite (`index_cache.db`), and in-process CPU embeddings via FastEmbed/ONNX.

### 1. Prerequisites
- **Python 3.11+**
- **Node.js 20+** & **npm**
- **Git** (available on system `PATH`)

### 2. Automated Setup (Recommended)

Clone the repository and run the automated setup script for your platform:

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

<details>
<summary><b>Or follow manual step-by-step setup</b></summary>

```bash
# 1. Create and activate a Python virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Build the React 19 administrative dashboard frontend
cd frontend
npm install
npm run build
cd ..
```
</details>

### 3. Start the Server
```bash
# Activate virtual environment (if not already active)
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Run ContextCortex with embedded vector store and local SQLite database
python3 main.py
```

The server starts on port `3000`:
- **Web Dashboard**: Access the admin interface at `http://localhost:3000/admin/`
- **MCP SSE Transport**: `http://localhost:3000/sse`
- **MCP Streamable HTTP Transport**: `http://localhost:3000/mcp`
- **OAuth Protected Resource Metadata**: `http://localhost:3000/.well-known/oauth-protected-resource`
- **Health Check**: `http://localhost:3000/health`

---

## 📡 Connecting MCP Clients

Connect any MCP client (VS Code, Cursor, Antigravity CLI, Claude Desktop, or Windsurf) using either Server-Sent Events (SSE) or Streamable HTTP.

### Server-Sent Events (SSE) Configuration (`claude_desktop_config.json` / Cursor)

#### Unauthenticated (Local Dev Bypass):
```json
{
  "mcpServers": {
    "contextcortex": {
      "url": "http://localhost:3000/sse"
    }
  }
}
```

#### Authenticated (API Key or Bearer Token):
```json
{
  "mcpServers": {
    "contextcortex": {
      "url": "http://localhost:3000/sse",
      "headers": {
        "Authorization": "Bearer cc_live_your_api_key_here"
      }
    }
  }
}
```

### Streamable HTTP Configuration

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

---

## 🌐 REST Administration APIs

ContextCortex provides REST endpoints under `/admin/api/*` protected by RBAC authentication (`Role.VIEWER`, `Role.EDITOR`, `Role.ADMIN`):

### Local Storage (`/admin/api/storage/*`)
| Endpoint | Method | Required Role | Description |
| :--- | :---: | :---: | :--- |
| `/admin/api/storage/upload` | `POST` | `editor` | Uploads and indexes a new file via `multipart/form-data` or JSON payload (`path`, `content`, `repo`, `category`). |
| `/admin/api/storage/file` | `PUT` | `editor` | Replaces existing file content and re-indexes vector representations. |
| `/admin/api/storage/file` | `DELETE` | `editor` | Deletes file from disk (`?path=...`) and purges vector embeddings and AST symbols. |
| `/admin/api/storage/file` | `GET` | `viewer` | Retrieves raw file content and metadata (`size_bytes`, `mtime`, `repo`, `category`). |
| `/admin/api/storage/tree` | `GET` | `viewer` | Explores storage directory hierarchy (`?folder=...`) with file and subdirectory listings. |

### Ingestion Catalog (`/admin/api/ingestion/*`)
| Endpoint | Method | Required Role | Description |
| :--- | :---: | :---: | :--- |
| `/admin/api/ingestion/catalog` | `GET` | `viewer` | Unified inventory across Git repos, monitored paths, and uploaded files. Supports `source_type`, `repo_name`, `path_prefix`, `file_extension`, `detail_level`. |

---

## 🔐 OAuth 2.1 & API Key Management

### Protected Resource Discovery
ContextCortex implements RFC 9728 Protected Resource Metadata. Clients can discover OAuth capabilities:
```bash
curl http://localhost:3000/.well-known/oauth-protected-resource
```
Response:
```json
{
  "resource": "https://contextcortex.local",
  "authorization_servers": ["https://auth.company.com/realms/master"],
  "scopes_supported": ["mcp:admin", "mcp:editor", "mcp:viewer"],
  "bearer_methods_supported": ["header"],
  "resource_documentation": "https://github.com/spelech/contextcortex"
}
```

### Generating API Keys (Admin API)
```bash
# Create a Viewer API key
curl -X POST http://localhost:3000/admin/api/auth/keys \
  -H "Authorization: Bearer cc_admin_key" \
  -H "Content-Type: application/json" \
  -d '{"name": "Cursor Agent Key", "role": "viewer"}'
```

---

## 📚 Documentation & Specifications

- [**Software Requirements Specification (`REQUIREMENTS.md`)**](REQUIREMENTS.md): Authoritative functional and non-functional requirements with test-traceability matrix and Mermaid ERD data models.
- [**System Architecture (`ARCHITECTURE.md`)**](ARCHITECTURE.md): FastMCP 2.0 transport topologies, component interaction diagrams, SQLAlchemy 2.0 schema ERD, and vector store data models.
- [**Developer Documentation (`DEVELOPER_DOCS.md`)**](DEVELOPER_DOCS.md): Setup, configuration, development workflow, and testing guidelines.
- [**Test Coverage Reports (`docs/TEST_COVERAGE.md`)**](docs/TEST_COVERAGE.md): Pytest, Vitest, and Playwright verification metrics.

---

## 🧪 Testing & Verification

Run the full automated test suites across backend and frontend:

```bash
# Python Backend Tests & Code Coverage
pytest -v --cov=app

# Synchronize Requirements Catalog
python3 scripts/generate_requirements.py

# Frontend Unit & Component Tests (Vitest)
cd frontend && npm run test

# Frontend End-to-End Tests (Playwright)
cd frontend && npx playwright test
```
