# ContextCortex (v2.22.0) <!-- x-release-please-version -->

[![Build and Publish Docker Image](https://github.com/spelech/contextcortex/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/spelech/contextcortex/actions/workflows/docker-publish.yml)
[![Docker Image](https://img.shields.io/badge/ghcr.io-spelech%2Fcontextcortex-blue?logo=docker)](https://github.com/spelech/contextcortex/pkgs/container/contextcortex)
[![Documentation](https://img.shields.io/badge/docs-GitHub%20Pages-blue?logo=github)](https://spelech.github.io/contextcortex/)
[![Python](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/MCP-2026--07--28-0052CC)](https://modelcontextprotocol.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

ContextCortex is a multi-repository Model Context Protocol (MCP) server providing **syntax-aware Code RAG**, **Hybrid Retrieval (Dense + BM25)**, **Tree-sitter AST chunking**, **Pluggable Dual-Engine Storage (PostgreSQL 16 + pgvector & SQLite)**, **MCP 2026-07-28 OAuth 2.1 + 3-Tier RBAC**, and **Universal Git Provider indexing** with an integrated Web Admin Dashboard.

<details>
<summary><b>🖼️ View Dashboard Components</b></summary>

| Overview | Git Repositories |
|:---:|:---:|
| ![Overview](docs/assets/desktop_overview.png) | ![Git Repos](docs/assets/desktop_git-repos.png) |
| **Codebase Navigator** | **Search & Inspector** |
| ![Codebase Navigator](docs/assets/desktop_codebase-navigator.png) | ![Search](docs/assets/desktop_search-inspector.png) |
| **Files & Storage** | **Settings** |
| ![Files & Storage](docs/assets/desktop_local-paths.png) | ![Settings](docs/assets/desktop_settings.png) |
| **Diagnostics & Logs** | **Add Repository Modal** |
| ![Diagnostics](docs/assets/desktop_diagnostics.png) | ![Add Repository Modal](docs/assets/desktop_add-repo-modal.png) |

</details>

<details open>
<summary><b>🎨 Multi-Theme Appearance (4 Palettes)</b></summary>

| **Deep Ocean** *(Dark Default)* | **Midnight Blue** *(Dark Space)* |
|:---:|:---:|
| ![Deep Ocean](docs/assets/theme_deep_ocean.png) | ![Midnight Blue](docs/assets/theme_midnight_blue.png) |
| *Petrol spruce `#07181b` with cyan `#0891b2` & mint* | *Obsidian navy `#0a0f1d` with royal blue `#3b82f6` & teal* |
| **Lavender Haze** *(Light Purple)* | **Amber Warmth** *(Light Sandstone)* |
|:---:|:---:|
| ![Lavender Haze](docs/assets/theme_lavender_haze.png) | ![Amber Warmth](docs/assets/theme_amber_warmth.png) |
| *Lilac canvas `#f5f3ff` with purple `#7c3aed` & fuchsia* | *Sandstone `#fdf8f4` with terracotta `#ea580c` & amber* |

</details>

---

## 🌟 Key Features

- **Pluggable Dual-Engine Storage**:
  - **PostgreSQL 16 + pgvector**: Production profile with `vector(384)` HNSW cosine indexing, `tsvector` GIN full-text search, and `psycopg3` pooling.
  - **SQLite + Qdrant**: Zero-configuration embedded profile with WAL journaling (`15000ms` busy timeout) and embedded or remote Qdrant RRF fusion.
  - **Live Vector Backend Switching**: Test and switch vector backends (`pgvector` <-> `Qdrant`) from the Settings UI or REST API without restarts.
- **MCP 2026-07-28 OAuth 2.1 & 3-Tier RBAC**:
  - **RFC 9728 Discovery**: Exposes `/.well-known/oauth-protected-resource` for OAuth resource indicators and scopes.
  - **JWT/OIDC & API Keys**: Validates RS256/ES256 bearer tokens via JWKS and SHA-256 hashed `cc_...` API keys across `admin`, `editor`, and `viewer` roles (`AUTH_ENABLED=false` enables local dev bypass).
- **FastMCP 2.0 Dual Transports**: Exposes SSE (`/sse` + `/messages/`) and Streamable HTTP (`/mcp`) with bounded JSON pagination across all tools and resources.
- **Universal Git Provider Indexing**:
  - Supports **GitHub**, **GitLab**, **Gitea/Forgejo**, **Bitbucket**, **Generic HTTP/HTTPS**, and **SSH (`git@...` / `ssh://...`)** with a 4-tier credential hierarchy.
  - **Shallow Clone & Commit Retention**: Configure persistent `--depth 1` clones (`keep_shallow`) for instant source navigation and retain `0..50` recent commits (`retain_commits_count`) for `get_recent_changes`.
- **Multi-Language AST & Forensic Intelligence**:
  - Extracts AST symbols, call graphs, and HTTP routes across **Python, TypeScript/JS/TSX, C#, COBOL, Go, Rust, Java, and C/C++**.
  - Provides multi-repo regex/literal `grep_code`, stack-trace `diagnose_issue` triage, cross-repo HTTP `trace_path`, and vector-chunk `read_file` reconstruction.
- **Managed Local Storage & Enterprise Private-CA Support**:
  - Upload, replace, preview, read, and delete files in `LOCAL_STORAGE_PATH` with immediate incremental indexing and path-traversal protection.
  - Bootstraps private CA certificates (`certs/*.crt`), custom OpenAI-compatible gateways (`OPENAI_API_URL`, `LLM_EXTRA_HEADERS`), and restricted-network mirror builds (`docker-compose.enterprise.yml`).

---

## 🛠️ MCP Tools, Resources & Prompts

See the full **[MCP Tools, Resources, and Pagination Reference](docs/mcp-tools-and-resources.md)** for complete schemas, [pagination conventions](docs/mcp-tools-and-resources.md#pagination-conventions), [tool parameter bounds](docs/mcp-tools-and-resources.md#mcp-tools-reference), [resource templates](docs/mcp-tools-and-resources.md#mcp-resources-and-templates), and [workflow prompts](docs/mcp-tools-and-resources.md#mcp-workflow-prompts).

### Tools & RBAC Permissions (19 Tools)

| Tool | Role | Key Parameters & Bounds | Description |
| :--- | :---: | :--- | :--- |
| `search_code` | `viewer` | `query`, `repo`, `language`, `top_k`/`limit` (`1..25`), `offset`, `max_snippet_chars` (`200..6000`), `mode` | Hybrid semantic + BM25 code search with AST signatures, permalinks, and bounded snippets. |
| `search_docs` | `viewer` | `query`, `repo`, `category`, `tag`, `top_k`/`limit` (`1..25`), `offset`, `max_snippet_chars` (`200..6000`), `mode` | Hybrid search across Markdown docs, runbooks, ADRs, summaries, and PDFs. |
| `find_symbol` | `viewer` | `name`, `repo`, `exact` (`True`), `limit` (`1..100`, default `30`), `offset` | Deterministic exact or substring AST symbol lookup without broad token scans. |
| `get_file_outline` | `viewer` | `filepath`, `repo`, `limit` (`1..500`, default `150`), `offset` | Returns deduplicated AST classes, functions, signatures, and line spans for a file. |
| `trace_path` | `viewer` | `symbol`, `repo`, `direction`, `depth` (`1..5`), `limit` (`1..200`, default `50`), `offset` | Traverses AST callers/callees and cross-repo HTTP route/client boundaries via BFS. |
| `find_routes` | `viewer` | `query`, `method`, `repo`, `limit` (`1..200`, default `50`), `offset` | Searches declared backend HTTP/API route endpoints across frameworks. |
| `find_api_callers` | `viewer` | `path`, `method`, `repo`, `limit` (`1..200`, default `50`), `offset` | Finds frontend and service HTTP client call sites invoking a target route pattern. |
| `list_repositories` | `viewer` | *None* | Lists registered Git repositories and monitored local paths with status and file totals. |
| `get_recent_changes` | `viewer` | `repo`, `filepath`, `symbol`, `limit` (`1..50`, default `10`), `offset` | Returns retained Git commits (capping `files_changed` at `<= 25` entries per commit). |
| `sync_repository` | `editor` | `repo` (opt) | Triggers asynchronous background Git delta sync for one repo or all sources. |
| `index_status` | `viewer` | *None* | Reports vector store health, point totals, active embedding models, and Git auth status. |
| `get_architecture` | `viewer` | `repo` (opt) | Synthesizes language distribution, manifests, entry points, modules, hub symbols, and ADRs. |
| `manage_adr` | `editor`/`viewer` | `action` (`list`\|`search`\|`get`\|`create`\|`update`\|`supersede`), `repo`, `query`, `limit` (`25`), `offset` | Queries, searches, creates, updates, or supersedes Architecture Decision Records. |
| `manage_local_file` | `editor`/`viewer` | `action` (`upload`\|`replace`\|`delete`\|`read`\|`preview`), `file_path`, `content`, `repo`, `category` | Manages files in `LOCAL_STORAGE_PATH` with immediate vector and AST indexing. |
| `what_is_ingested` | `viewer` | `source_type`, `repo_name`, `path_prefix`, `file_extension`, `detail_level`, `include_files`, `limit` (`1..500`), `offset` | Inspects ingested sources with per-source paginated file lists when `include_files=True`. |
| `read_file` | `viewer` | `path`, `repo`, `start_line`, `end_line` | Reads bounded 1-based line ranges (`total_lines`, `has_more`, `next_start_line`). |
| `summarize_file` | `viewer` | `path`, `repo`, `force_refresh` (`False`) | Retrieves a cached summary or generates a structured LLM executive file summary. |
| `grep_code` | `viewer` | `pattern`, `repo`, `path_glob`, `is_regex`, `case_sensitive`, `context_lines` (`0..10`), `max_results`/`limit` (`1..100`), `offset` | Literal/regex search with AST attribution; truncates lines `> 400` chars cleanly. |
| `diagnose_issue` | `viewer` | `issue_text`, `repo`, `context_lines` (`1..15`), `limit` (`1..20`) | Forensic triage resolving stack traces, error literals, routes, and semantic candidates. |

### Resources & Paginated Resource Templates

| Resource URI / Template | MIME Type | Pagination / Scope | Description |
| :--- | :---: | :---: | :--- |
| `knowledge://catalog/summary` | `application/json` | Compact (`<= 40` sample files) | Global catalog summary plus `resource_templates` discovery metadata. |
| `knowledge://repo/{repo}/summary` | `application/json` | Per-repo | Status, commit SHA, language breakdown, symbol/route/ADR counts, and sub-resource URIs. |
| `knowledge://repo/{repo}/architecture` | `application/json` | Per-repo | Synthesized architecture overview (manifests, entry points, modules, hub symbols). |
| `knowledge://repo/{repo}/files/{page}` | `application/json` | `100` files / page | 1-indexed paginated file inventory (`total_files`, `total_pages`, `has_more`, `next_uri`). |
| `knowledge://repo/{repo}/routes/{page}` | `application/json` | `50` routes / page | 1-indexed paginated API routes (`total_routes`, `total_pages`, `has_more`, `next_uri`). |
| `knowledge://repo/{repo}/adrs` | `application/json` | Per-repo | Architecture Decision Records registered for `{repo}`. |

### Workflow Prompts (5 Prompts)

| Prompt Name | Arguments | Description |
| :--- | :--- | :--- |
| `search_infrastructure_docs` | `topic` | Guided workflow across `search_docs`, `manage_adr`, and `read_file` for infra configs. |
| `find_implementation_symbol` | `symbol`, `repo` (opt) | Locates symbol definitions, exact line slices, and caller/callee paths. |
| `onboard_repository` | `repo` | Maps architecture, HTTP routes, file outlines, and recent commits for `{repo}`. |
| `triage_error` | `issue_text`, `repo` (opt) | Diagnoses stack traces or failing routes down to root-cause lines and commits. |
| `investigate_change_impact` | `symbol`, `repo` (opt) | Evaluates blast radius across internal callers, cross-repo API clients, and tests. |

---

## ⚙️ Environment Variables

| Variable | Description | Default |
| :--- | :--- | :--- |
| `DATABASE_URL` | SQLAlchemy URL (`postgresql+psycopg://...` or `sqlite:////app/data/index_cache.db`) | `sqlite:////app/data/index_cache.db` |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | PostgreSQL container credentials (`POSTGRES_PORT` default `5432`) | `contextcortex` / `cortexsecret` |
| `LOCAL_STORAGE_PATH` | Managed local storage root for direct uploads and incremental indexing | `/app/data/storage` |
| `AUTH_ENABLED` | Enable MCP 2026-07-28 OAuth 2.1 and API Key RBAC | `false` |
| `AUTH_OIDC_ISSUER` / `AUTH_JWKS_URI` | OIDC Issuer URL and optional custom JWKS URI override | `None` |
| `AUTH_RESOURCE_INDICATOR` | RFC 8707 / RFC 9728 OAuth Resource Indicator | `https://contextcortex.local` |
| `ADMIN_INITIAL_KEY` | Bootstrap admin API key on container startup | `None` |
| `VECTOR_STORE_PROVIDER` | Vector backend (`pgvector` or `qdrant`) | `pgvector` (PG) / `qdrant` (SQLite) |
| `VECTOR_STORE_MODE` | Vector mode (`embedded` or `remote`) | `embedded` (Qdrant) / `remote` (PG) |
| `COLLECTION_NAME` | Active vector collection name | `knowledge_rag_v1` |
| `QDRANT_URL` / `QDRANT_STORAGE_PATH` | Remote Qdrant URL or embedded storage path | `http://localhost:6333` / `/app/data/qdrant_storage` |
| `OPENAI_API_URL` / `OPENAI_API_KEY` | OpenAI-compatible gateway base URL and Bearer key | `http://litellm:4000/v1` / `dummy` |
| `LLM_EXTRA_HEADERS` | JSON object of custom HTTP headers sent to the AI gateway | `None` |
| `EXTRA_CA_CERTS_DIR` | Directory of private `*.crt` CA certificates trusted at startup ([certs/README.md](certs/README.md)) | `/certs` |
| `GITHUB_TOKEN` / `GITLAB_TOKEN` | Optional global Personal Access Tokens for private Git hosts | `None` |
| `CACHE_DB_PATH` | Persistent SQLite database path when `DATABASE_URL` is unset | `/app/data/index_cache.db` |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | Character chunk length and overlap window | `1500` / `200` |

---

## 🚀 Three Ways to Deploy ContextCortex

| Deployment Mode | Relational Metadata DB | Vector Store | Best For |
| :--- | :--- | :--- | :--- |
| **1. Docker Compose** *(Recommended)* | **PostgreSQL 16** (or SQLite) | **`pgvector`** or **Qdrant** | Production, homelab, and enterprise containers (`docker-compose.yml`) |
| **2. Windows Portable Bundle** | **Embedded PostgreSQL 16** | **Embedded `pgvector`** or **Qdrant** | Zero-admin Windows workstations (`scripts/build_portable_windows.ps1`) |
| **3. Local Python (`venv`)** | **SQLite** (or external Postgres) | **Embedded Qdrant** | Local development and lightweight CLI/MCP workflows |

### Mode 1: Docker Compose (Recommended)

```bash
git clone git@github.com:spelech/contextcortex.git
cd contextcortex
cp .env.example .env
docker compose up -d
```

| Sub-Configuration | Relational DB (`DATABASE_URL`) | Vector Store | Configuration |
| :--- | :--- | :--- | :--- |
| **1A. PostgreSQL 16 + `pgvector`** *(Default)* | `postgresql+psycopg://...@postgres:5432/contextcortex` | `pgvector` (`remote`) | Default in `docker-compose.yml`. |
| **1B. PostgreSQL + Remote Qdrant** | `postgresql+psycopg://...` | `qdrant` (`remote`) | Set `VECTOR_STORE_PROVIDER=qdrant`, `QDRANT_URL=http://qdrant:6333`. |
| **1C. PostgreSQL + Embedded Qdrant** | `postgresql+psycopg://...` | `qdrant` (`embedded`) | Stores vectors on `/app/data/vector_storage`. |
| **1D. Single-Container SQLite + Qdrant** | `sqlite:////app/data/index_cache.db` | `qdrant` (`embedded`) | Use `docker-compose.enterprise.yml` overrides without Postgres. |

Open `http://localhost:3000/admin/` -> **Settings** -> **AI & Model Gateway** to test `OPENAI_API_URL` and select your Embedding, Chat, and Vision OCR models. For corporate TLS proxies, private CAs (`certs/*.crt`), and internal package mirrors, see [Restricted-Network Builds & Enterprise Deployment](docs/guide/enterprise-build.md):

```bash
docker compose -f docker-compose.yml -f docker-compose.enterprise.yml up -d --build
```

### Mode 2: Windows Standalone Portable Deployment

Packages a frozen `contextcortex.exe`, user-space **PostgreSQL 16**, pre-compiled **`pgvector`**, private CA loader, and React Dashboard into `dist\contextcortex-windows-x64`:

```powershell
.\scripts\build_portable_windows.ps1
.\dist\contextcortex-windows-x64\start-contextcortex.bat
```

Set `PORTABLE_POSTGRES_ENABLED=true` (default `127.0.0.1:54329` + `pgvector`) or `PORTABLE_POSTGRES_ENABLED=false` with `VECTOR_STORE_PROVIDER=qdrant` in `dist\contextcortex-windows-x64\.env`.

### Mode 3: Local Python (`venv`)

Requires **Python 3.11+**, **Node.js 20+**, and **Git**:

```bash
git clone git@github.com:spelech/contextcortex.git
cd contextcortex
./setup.sh            # Windows PowerShell: .\setup.ps1
source venv/bin/activate
python3 main.py
```

Default endpoints on port `3000`:
- **Web Dashboard**: `http://localhost:3000/admin/`
- **MCP Streamable HTTP / SSE**: `http://localhost:3000/mcp` and `http://localhost:3000/sse`
- **OAuth Metadata & Health**: `http://localhost:3000/.well-known/oauth-protected-resource`, `/health`, `/ready`

---

## 📡 Connecting MCP Clients

Configure Cursor, VS Code, Antigravity CLI, Claude Desktop, or Windsurf via Streamable HTTP (`/mcp`) or SSE (`/sse`):

```json
{
  "mcpServers": {
    "contextcortex": {
      "url": "http://localhost:3000/mcp",
      "headers": {
        "Authorization": "Bearer cc_live_your_api_key_here"
      }
    }
  }
}
```

*(Omit `headers` when running locally with `AUTH_ENABLED=false`.)*

---

## 🌐 REST Administration APIs & OAuth 2.1

All `/admin/api/*` routes enforce RBAC (`viewer`, `editor`, `admin`):

| Endpoint Group | Routes | Role | Purpose |
| :--- | :--- | :---: | :--- |
| **Navigator** | `GET /admin/api/navigator/{tree,file-outline,symbol-impact}` | `viewer` | File hierarchy, AST outlines, and caller/callee impact graphs. |
| **Local Storage** | `POST /upload`, `PUT\|DELETE\|GET /file`, `GET /tree` under `/admin/api/storage` | `editor` / `viewer` | Upload, replace, delete, read, and browse managed storage files. |
| **Ingestion Catalog** | `GET /admin/api/ingestion/catalog` | `viewer` | Multi-source inventory across Git repos, watched paths, and storage. |
| **API Keys** | `POST /admin/api/auth/keys` | `admin` | Issue scoped `cc_...` keys (`viewer`, `editor`, `admin`). |

```bash
# Discover RFC 9728 OAuth metadata
curl http://localhost:3000/.well-known/oauth-protected-resource

# Issue a Viewer API key
curl -X POST http://localhost:3000/admin/api/auth/keys \
  -H "Authorization: Bearer cc_admin_key" -H "Content-Type: application/json" \
  -d '{"name": "Agent Viewer Key", "role": "viewer"}'
```

---

## 📚 Documentation & Verification

- **[Interactive Documentation Site (VitePress)](https://spelech.github.io/contextcortex/)** (`npm run docs:dev` / `npm run docs:build`)
- **[MCP Tools, Resources, and Pagination Reference (`docs/mcp-tools-and-resources.md`)](docs/mcp-tools-and-resources.md)**
- **[Restricted-Network & Enterprise Builds (`docs/guide/enterprise-build.md`)](docs/guide/enterprise-build.md)**
- **[Software Requirements (`REQUIREMENTS.md`)](REQUIREMENTS.md)** | **[Architecture (`ARCHITECTURE.md`)](ARCHITECTURE.md)** | **[Developer Docs (`DEVELOPER_DOCS.md`)](DEVELOPER_DOCS.md)** | **[Test Coverage (`docs/TEST_COVERAGE.md`)](docs/TEST_COVERAGE.md)**

```bash
# Backend Pytest Suite
pytest -v --cov=app

# Frontend Unit (Vitest) & E2E (Playwright) Suites
cd frontend && npm run test && npx playwright test
```
