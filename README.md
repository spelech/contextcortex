# Notes & Code RAG MCP Server (v2.4.1)

[![Build and Publish Docker Image](https://github.com/spelech/notes-rag-mcp/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/spelech/notes-rag-mcp/actions/workflows/docker-publish.yml)
[![Docker Image](https://img.shields.io/badge/ghcr.io-spelech%2Fnotes--rag--mcp-blue?logo=docker)](https://github.com/spelech/notes-rag-mcp/pkgs/container/notes-rag-mcp)

A high-performance, multi-repo Model Context Protocol (MCP) server providing **syntax-aware Code RAG**, **Hybrid Retrieval (Dense + BM25)**, **Tree-sitter AST chunking**, and **Ephemeral GitHub repo indexing** with an integrated Web Admin Dashboard and real-time Diagnostic Observability.

![Notes & Code RAG Admin Dashboard](docs/assets/dashboard.jpg)

---

## 🌟 Key Features

- **FastMCP 2.0 Native Architecture**: Built on the official Model Context Protocol Python SDK 2.0.0+ (`FastMCP`), supporting modern decorator patterns, typed schemas, dynamic catalog resources, and custom agent prompts.
- **Dual MCP Transports**:
  - **Server-Sent Events (SSE)**: Full streaming events at `/sse` with POST message routing at `/messages/`.
  - **Streamable HTTP**: Bidirectional JSON-RPC transport endpoint at `/mcp`.
- **Universal Git Provider Support**:
  - Ingest repositories from **any source where Git lives**: **GitHub**, **GitLab (Cloud, Enterprise & Self-Hosted)**, **Gitea & Forgejo**, **Bitbucket (Cloud & Server)**, and **Generic Git HTTP/HTTPS**.
  - **Provider-Aware Permalinks**: Automatically generates exact deep-links for code results (`/blob/`, `/-/blob/`, `/src/branch/`, `/src/commit/`, `/src/#lines-`).
  - **Custom Git Host Credential Vault**: Register per-host tokens and authentication types for private internal domains (e.g. `gitlab.company.internal` or `http://git.lan:3000`).
- **AST-Aware Code Chunking (Tree-sitter)**: Understands syntax structures across Python, TypeScript/JavaScript, Go, Rust, C#, C++, Java, Ruby, PHP, and more. Chunks along class, method, and function boundaries with exact line numbers and symbol names.
- **Native Qdrant Hybrid Retrieval (Dense + Sparse BM25)**: Uses Qdrant named multi-vectors combining CPU-optimized dense embeddings (`BAAI/bge-small-en-v1.5`, 384d) with sparse BM25 vectors (`Qdrant/bm25` via FastEmbed) fused with **Reciprocal Rank Fusion (RRF)**.
- **Ephemeral Repository Ingestion**: The server performs authenticated shallow clones (`--depth 1`), extracts AST symbols and hybrid vectors, and **immediately removes the cloned repository from disk** to conserve storage.
- **Multi-Tier Git Authentication Hierarchy**:
  1. Per-repository override token & optional username.
  2. Domain-level Custom Git Host Vault (`git_host_credentials`).
  3. Global provider tokens (`GITHUB_TOKEN`, `GITLAB_TOKEN`, `GITEA_TOKEN` in DB or Settings UI).
  4. Environment variable fallback.
- **Fast Deterministic Symbol Lookup**: Built-in SQLite symbol table (`ast_symbols`) powers instantaneous symbol searches (`find_symbol`) and file outlines (`get_file_outline`) without token bloat.
- **Diagnostic Logging & Observability**: In-memory ring buffer (500 events) capturing server warnings, errors, indexing lifecycle events, and expandable stack traces with a REST API (`/admin/api/logs`).
- **Modern Tabbed Web Dashboard (`/admin/`)**:
  - **Overview**: Real-time stats, vector counts, AST symbols, model specs, topic tag cloud, and manual full reindexing trigger.
  - **Git Repositories**: Register repos across GitHub, GitLab, Gitea, Bitbucket, or Generic Git, trigger shallow clone syncs, inspect commit SHAs, and manage sources.
  - **Local Paths**: Monitor local workspaces and notes vaults with recursive directory scanning and filesystem browser modal.
  - **Search & Inspector**: Interactive live hybrid search tester with RRF score previews, target type toggle (Code vs Docs), and syntax highlighted results.
  - **Settings**: Multi-provider token cards (GitHub, GitLab, Gitea), GitHub rate limit monitor, and interactive Custom Git Host Credential Vault table/modal.
  - **Diagnostics & Logs**: Real-time log viewer with level filtering (ALL, INFO, WARNING, ERROR, DEBUG), keyword search, traceback modal/drawer, and buffer clearing.

---

## 🛠️ MCP Tools, Resources & Prompts

### Tools
| Tool | Parameters | Description |
| :--- | :--- | :--- |
| `search_code` | `query` (str), `repo` (str, opt), `language` (str, opt), `limit` (int, default 5) | Hybrid semantic + BM25 code search. Returns code blocks with line ranges & clickable GitHub permalinks. |
| `search_docs` | `query` (str), `repo` (str, opt), `category` (str, opt), `tag` (str, opt), `limit` (int, default 5) | Hybrid search across markdown notes, system architecture, and runbooks. |
| `find_symbol` | `name` (str), `repo` (str, opt), `exact` (bool, default True), `limit` (int, default 10) | Instant exact or prefix AST symbol lookup (functions, classes, structs, interfaces). |
| `get_file_outline` | `filepath` (str), `repo` (str, opt) | Returns the AST structure (classes, methods, signatures, lines) without full file token costs. |
| `list_repositories` | *None* | Lists all registered Git repositories and local paths with commit SHAs and indexing status. |
| `sync_repository` | `repo` (str, opt) | Triggers background shallow clone sync for a specific repository or all sources. |
| `index_status` | *None* | Returns vector counts, collection status, embedding models, and GitHub rate limits. |

### Resources
| Resource URI | MIME Type | Description |
| :--- | :--- | :--- |
| `notes://catalog/summary` | `text/markdown` | Dynamic catalog of all indexed repositories, document distributions, and AST symbol totals. |

### Prompts
| Prompt Name | Arguments | Description |
| :--- | :--- | :--- |
| `search_infrastructure_docs` | `topic` (str) | Guided agent workflow to retrieve system architecture, container port mappings, and reverse proxy configs. |
| `find_implementation_symbol` | `symbol` (str), `repo` (str, opt) | Guided agent workflow to locate symbol definitions, class signatures, and implementations. |

---

## ⚙️ Environment Variables

| Variable | Description | Default |
| :--- | :--- | :--- |
| `EMBEDDING_PROVIDER` | Embedding engine (`local` for in-process ONNX, `api` for LiteLLM/OpenAI) | `local` |
| `EMBEDDING_MODEL` | FastEmbed dense model name | `BAAI/bge-small-en-v1.5` |
| `SPARSE_MODEL` | FastEmbed sparse BM25 model name | `Qdrant/bm25` |
| `QDRANT_URL` | URL to the Qdrant vector database | `http://qdrant:6333` |
| `COLLECTION_NAME` | Qdrant collection name | `notes_rag_v2` |
| `GITHUB_TOKEN` | Optional GitHub Personal Access Token for rate limits & private repos | `None` |
| `VAULT_PATH` | Default path to the markdown documentation directory | `/docs` |
| `CACHE_DB_PATH` | Path to persistent SQLite cache database | `/app/data/index_cache.db` |
| `CHUNK_SIZE` | Maximum character length per chunk | `1500` |
| `CHUNK_OVERLAP` | Character overlap between consecutive chunks | `200` |

---

## 🚀 Running via Docker

### Docker Compose
```yaml
services:
  notes-rag-mcp:
    image: ghcr.io/spelech/notes-rag-mcp:latest
    container_name: notes-rag-mcp
    restart: unless-stopped
    ports:
      - "8021:3000"
    environment:
      - EMBEDDING_PROVIDER=local
      - EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
      - QDRANT_URL=http://qdrant:6333
      - GITHUB_TOKEN=ghp_your_optional_token
      - VAULT_PATH=/docs
    volumes:
      - /path/to/my/docs:/docs:ro
      - ./data:/app/data
```

---

## 📡 Connecting MCP Clients

Connect any MCP client (VS Code, Cursor, Antigravity CLI, Claude Desktop, or Windsurf) using either Server-Sent Events (SSE) or Streamable HTTP.

### Server-Sent Events (SSE) Configuration (`claude_desktop_config.json` / Cursor)
```json
{
  "mcpServers": {
    "notes-rag": {
      "url": "http://localhost:3000/sse"
    }
  }
}
```

### Streamable HTTP Configuration
```json
{
  "mcpServers": {
    "notes-rag-http": {
      "url": "http://localhost:3000/mcp"
    }
  }
}
```

---

## 🧪 Testing & Verification

Run the full automated test suites across backend and frontend:

```bash
# Python Backend Tests & Code Coverage
pytest -v --cov=app

# Frontend Unit & Component Tests (Vitest)
cd frontend && npm run test

# Frontend End-to-End Tests (Playwright)
cd frontend && npx playwright test
```
