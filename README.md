# Notes & Code RAG MCP Server (v2.2.0)

[![Build and Publish Docker Image](https://github.com/spelech/notes-rag-mcp/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/spelech/notes-rag-mcp/actions/workflows/docker-publish.yml)
[![Docker Image](https://img.shields.io/badge/ghcr.io-spelech%2Fnotes--rag--mcp-blue?logo=docker)](https://github.com/spelech/notes-rag-mcp/pkgs/container/notes-rag-mcp)

A high-performance, multi-repo Model Context Protocol (MCP) server providing **syntax-aware Code RAG**, **Hybrid Retrieval (Dense + BM25)**, **Tree-sitter AST chunking**, and **Ephemeral GitHub repo indexing** with an integrated Web Admin Dashboard.

![Notes & Code RAG Admin Dashboard](docs/assets/dashboard.jpg)

---

## 🌟 Key Features

- **AST-Aware Code Chunking (Tree-sitter)**: Understands syntax structures across Python, TypeScript/JavaScript, Go, Rust, C#, C++, Java, Ruby, PHP, and more. Chunks along class, method, and function boundaries with exact line numbers and symbol names.
- **Native Qdrant Hybrid Retrieval (Dense + Sparse BM25)**: Uses Qdrant named multi-vectors combining CPU-optimized dense embeddings (`BAAI/bge-small-en-v1.5`, 384d) with sparse BM25 vectors (`Qdrant/bm25` via FastEmbed) fused with **Reciprocal Rank Fusion (RRF)**.
- **Ephemeral GitHub Repository Ingestion**: Register GitHub repositories and branches in the Admin UI. The server performs authenticated shallow clones (`--depth 1`), extracts AST symbols and hybrid vectors, and **immediately removes the cloned repository from disk** to save container storage.
- **GitHub Token & Rate Limit Management**: Configure a GitHub Personal Access Token via `GITHUB_TOKEN` environment variable or directly in the Admin UI settings to boost rate limits to 5,000 req/hr and access private repositories.
- **Fast Deterministic Symbol Lookup**: Built-in SQLite symbol table (`ast_symbols`) powers instantaneous symbol searches (`find_symbol`) and file outlines (`get_file_outline`) without token bloat.
- **Specialized MCP Agent Tools**:
  - `search_code`: Hybrid semantic + BM25 search over code functions and logic with line numbers and clickable GitHub links.
  - `search_docs`: Dedicated search across markdown notes and architecture runbooks.
  - `find_symbol`: Instant exact/fuzzy symbol definitions from AST index.
  - `get_file_outline`: File symbol hierarchy without full token context costs.
  - `list_repositories`: Summary of all indexed Git repos and local paths.
  - `sync_repository`: On-demand re-sync for a specific repo or all sources.
  - `index_status`: Global vector stats and GitHub rate limits.
- **Modular Architecture & Strict Validation**: Refactored backend (`app/`) with strict `Pydantic` validation for API schemas and MCP tools.
- **MCP 2.0.0 Compatible**: Built natively against the newest Model Context Protocol SDK 2.0.0.
- **Modern Tabbed Web Dashboard (`/admin/`)**:
  - **Overview**: Real-time stats, vector counts, AST symbols, model specs, and topic tag cloud.
  - **Git Repositories**: Register repos, trigger shallow clone syncs, inspect commit SHAs, and manage sources.
  - **Local Paths**: Monitor local workspaces and notes vaults with recursive scan options.
  - **Search & Inspector**: Interactive live hybrid search tester with RRF score previews and syntax highlighted results.
  - **Settings**: GitHub token configuration and rate limit status monitor.

---

## 🛠️ MCP Tools, Resources & Prompts

### Tools
| Tool | Description |
| :--- | :--- |
| `search_code` | Hybrid code search (`query`, `repo`, `language`, `limit`). Returns code blocks with line ranges & GitHub permalinks. |
| `search_docs` | Hybrid documentation search (`query`, `repo`, `category`, `tag`, `limit`). |
| `find_symbol` | Instant AST symbol lookup (`name`, `repo`, `exact`, `limit`). |
| `get_file_outline` | Returns the AST structure (classes, methods, lines) for a file (`filepath`, `repo`). |
| `list_repositories` | Lists all registered Git repositories and local paths with commit SHAs and status. |
| `sync_repository` | Triggers background sync for a specific repository (`repo`). |
| `index_status` | Returns vector counts, collection status, embedding models, and GitHub rate limits. |

### Resources
- `notes://catalog/summary`: Markdown catalog of all indexed repositories, document distributions, and AST symbols.

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

Connect any MCP client (VS Code, Cursor, Antigravity CLI, or Claude Desktop) to the Server-Sent Events (SSE) endpoint:

```json
{
  "mcpServers": {
    "notes-rag": {
      "url": "http://localhost:3000/sse",
      "headers": {}
    }
  }
}
```
