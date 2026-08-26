# Developer Documentation: ContextCortex (v2.11.0)

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
| `VECTOR_STORE_PROVIDER` | Vector database backend (`qdrant` or `chroma`) | `qdrant` |
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
│   │   ├── routers/       # Dedicated subrouters (repositories.py, settings.py, graph.py)
│   │   ├── routes.py      # Main router aggregator and health checks
│   │   └── webhooks.py    # Multi-provider webhook endpoint and HMAC validation
│   ├── mcp/               # FastMCP 2.0 dual-transport server
│   │   ├── handlers/      # Modular tool handlers (search, symbol, repo, route, architecture)
│   │   ├── mcp_server.py  # FastMCP server lifecycle & session registry
│   │   └── tools.py       # Tool registry and handler dispatcher
│   ├── models/            # Pydantic schema validation models
│   │   └── schemas.py     # Request/response schemas for APIs and MCP
│   └── services/          # Modular business logic services
│       ├── chunking/      # Tree-sitter loaders, token chunkers, AST/route extractors
│       ├── database/      # SQLite WAL connection, credential vault, ADRs, sync configs
│       ├── indexing/      # Git/local syncers, file processor, state notifications
│       ├── topology/      # Graph topology builder, node details, BFS helpers
│       ├── vector_store/  # Qdrant and ChromaDB pluggable vector store implementations
│       ├── git_manager.py # Ephemeral shallow git clone, token masking, permalinks
│       ├── embeddings.py  # FastEmbed dense (384d) & sparse BM25 multi-vector engine
│       ├── search.py      # Hybrid search & Reciprocal Rank Fusion (RRF) reranker
│       ├── poller.py      # Background scheduled repo SHA poller daemon
│       ├── adr.py         # MADR / Nygard format ADR ingestion and lifecycle
│       ├── architecture.py# Codebase entry point, language distribution synthesis
│       └── logger.py      # In-memory 500-event ring buffer diagnostic logger
├── tests/                 # Backend pytest test suite (277 tests, 88% coverage)
│   ├── backend/           # Unit and integration test modules
│   ├── test_poller.py     # Background poller tests
│   └── test_webhooks.py   # Multi-provider webhook tests
├── frontend/              # Web Admin Dashboard (React 19, TypeScript, Vite)
│   ├── src/               # React components and modular sub-components
│   │   ├── components/    # Sub-component trees (git/, settings/, topology/)
│   │   ├── styles/        # Modular CSS stylesheets (base.css, components.css, topology.css)
│   │   └── tests/         # Vitest component unit tests (82 tests, 87% coverage)
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
      "url": "http://localhost:3000/sse"
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
      "url": "http://localhost:3000/mcp"
    }
  }
}
```

### Available MCP Tools (11 Tools):
- `search_code(query="JWT authentication handler", repo="backend-api")`
- `search_docs(query="caddy reverse proxy configuration")`
- `find_symbol(name="extract_symbols_and_chunks", exact=true)`
- `get_file_outline(filepath="app/services/search.py")`
- `list_repositories()`
- `sync_repository(repo="backend-api")`
- `index_status()`
- `get_architecture(repo="backend-api")`
- `manage_adr(action="list", repo="backend-api")`
- `get_code_routes(repo="backend-api")`
- `trace_call_path(target="authenticate_user", repo="backend-api")`

### Available MCP Resources:
- `knowledge://catalog/summary`

### Available MCP Prompts:
- `search_infrastructure_docs(topic="docker-compose network topology")`
- `find_implementation_symbol(symbol="execute_hybrid_search")`
