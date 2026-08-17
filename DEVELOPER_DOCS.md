# Developer Documentation (v2.6.0)


This document provides instructions for developing, testing, configuring, and running the Knowledge RAG MCP Server locally.

---

## 🛠️ Prerequisites

- **Python 3.11+**
- **Node.js 20+** & **npm** (for the React 19 frontend)
- **Git** (for shallow repository cloning)
- **Vector Database**: Qdrant (local/Docker or embedded) or ChromaDB (embedded/disk or remote)
- **FastEmbed** (included in `requirements.txt` for in-process ONNX CPU embeddings)

---

## 💻 Local Setup

1. **Clone the repository:**
   ```bash
   git clone git@github.com:spelech/knowledge-rag-mcp.git
   cd knowledge-rag-mcp
   ```

2. **Create a virtual environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows use `venv\Scripts\activate`
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
   export EMBEDDING_PROVIDER="local"
   export EMBEDDING_MODEL="BAAI/bge-small-en-v1.5"
   export SPARSE_MODEL="Qdrant/bm25"
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
# Run all backend unit and integration tests
pytest -v

# Run backend tests with code coverage report
pytest -v --cov=app --cov-report=term-missing
```

### Frontend Tests (React / TypeScript)
```bash
cd frontend

# Run unit and component tests via Vitest
npm test

# Run component tests with code coverage
npm run test:coverage

# Run end-to-end user journey tests via Playwright
npx playwright test
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

## 📁 Project Structure

```
knowledge-rag-mcp/
├── main.py                # FastAPI entry point, lifespan manager & FastMCP route mounting
├── app/                   # Backend modular architecture
│   ├── api/               # FastAPI REST routes (repos, paths, search, logs, stats, vector-store)
│   ├── mcp/               # FastMCP 2.0 server, tools, resources, and prompt templates
│   ├── models/            # Pydantic schema validation models
│   └── services/          # Core services (chunker, embeddings, db, git_manager, logger, search, vector_store)
├── tests/                 # Backend pytest test suite
│   └── backend/           # Unit and integration tests (>95% coverage)
├── frontend/              # Web Admin Dashboard - Knowledge RAG Hub (React 19, TypeScript, Vite)
│   ├── src/               # React components, contexts, and styles
│   │   └── tests/         # Vitest component unit tests
│   ├── e2e/               # Playwright E2E test specs (13 full test workflows)
│   └── dist/              # Compiled production distribution assets
├── requirements.txt       # Python dependencies (FastMCP 2.0, FastAPI, Qdrant, ChromaDB, FastEmbed)
├── Dockerfile             # Container definition with Python 3.11 & Git
├── ARCHITECTURE.md        # Deep architectural design specification
└── DEVELOPER_DOCS.md      # Local developer setup and test guide
```

---

## 📡 Connecting MCP Clients

Connect any MCP client supporting **Server-Sent Events (SSE)** or **Streamable HTTP**:

### 1. Server-Sent Events (SSE)
- **SSE Stream Endpoint**: `http://localhost:3000/sse`
- **Message Exchange Endpoint**: `http://localhost:3000/messages/`

Example configuration (`claude_desktop_config.json` / Cursor):
```json
{
  "mcpServers": {
    "knowledge-rag-sse": {
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
    "knowledge-rag-http": {
      "url": "http://localhost:3000/mcp"
    }
  }
}
```

### Available MCP Tools:
- `search_code(query="JWT authentication handler", repo="backend-api")`
- `search_docs(query="caddy reverse proxy configuration")`
- `find_symbol(name="extract_symbols_and_chunks", exact=true)`
- `get_file_outline(filepath="chunker.py")`
- `list_repositories()`
- `sync_repository(repo="backend-api")`
- `index_status()`

### Available MCP Resources:
- `knowledge://catalog/summary`


### Available MCP Prompts:
- `search_infrastructure_docs(topic="docker-compose network topology")`
- `find_implementation_symbol(symbol="execute_hybrid_search")`
