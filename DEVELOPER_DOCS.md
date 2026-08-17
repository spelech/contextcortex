# Developer Documentation (v2.3.0)

This document provides instructions for developing, testing, configuring, and running the Notes & Code RAG MCP Server locally.

---

## 🛠️ Prerequisites

- **Python 3.11+**
- **Node.js 20+** & **npm** (for the React 19 frontend)
- **Git** (for shallow repository cloning)
- **Qdrant** (local instance or Docker container)
- **FastEmbed** (included in `requirements.txt` for in-process ONNX CPU embeddings)

---

## 💻 Local Setup

1. **Clone the repository:**
   ```bash
   git clone git@github.com:spelech/notes-rag-mcp.git
   cd notes-rag-mcp
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

5. **Start Qdrant Vector Database:**
   ```bash
   docker run -d --name qdrant -p 6333:6333 -p 6334:6334 \
       -v $(pwd)/qdrant_storage:/qdrant/storage \
       qdrant/qdrant:latest
   ```

6. **Set Environment Variables (Optional):**
   ```bash
   export QDRANT_URL="http://localhost:6333"
   export COLLECTION_NAME="notes_rag_v2"
   export EMBEDDING_PROVIDER="local"
   export EMBEDDING_MODEL="BAAI/bge-small-en-v1.5"
   export SPARSE_MODEL="Qdrant/bm25"
   export GITHUB_TOKEN="ghp_your_token" # Optional: For higher rate limits & private repos
   ```

7. **Run the server:**
   ```bash
   python main.py
   ```
   The server starts on port `3000`, initializes SQLite tables (`index_cache.db`), configures Qdrant named multi-vectors (Dense + BM25 Sparse), mounts `/admin/` static files, and binds both `/sse` and `/mcp` FastMCP transport endpoints.

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
| `EMBEDDING_PROVIDER` | Embedding engine (`local` for in-process ONNX, `api` for LiteLLM/OpenAI) | `local` |
| `EMBEDDING_MODEL` | FastEmbed dense model name | `BAAI/bge-small-en-v1.5` |
| `SPARSE_MODEL` | FastEmbed sparse BM25 model name | `Qdrant/bm25` |
| `QDRANT_URL` | URL to the Qdrant vector database | `http://localhost:6333` |
| `COLLECTION_NAME` | Qdrant collection name | `notes_rag_v2` |
| `GITHUB_TOKEN` | Optional GitHub Personal Access Token for rate limits & private repos | `None` |
| `VAULT_PATH` | Default path to the markdown documentation directory | `/docs` |
| `CACHE_DB_PATH` | Path to persistent SQLite cache database | `/app/data/index_cache.db` |
| `CHUNK_SIZE` | Maximum character length per chunk | `1500` |
| `CHUNK_OVERLAP` | Character overlap between consecutive chunks | `200` |

---

## 📁 Project Structure

```
notes-rag-mcp/
├── main.py                # FastAPI entry point, lifespan manager & FastMCP route mounting
├── app/                   # Backend modular architecture
│   ├── api/               # FastAPI REST routes (repos, paths, search, logs, stats)
│   ├── mcp/               # FastMCP 2.0 server, tools, resources, and prompt templates
│   ├── models/            # Pydantic schema validation models
│   └── services/          # Core services (chunker, embeddings, db, git_manager, logger, search)
├── tests/                 # Backend pytest test suite
│   └── backend/           # Unit and integration tests (>95% coverage)
├── frontend/              # Web Admin Dashboard (React 19, TypeScript, Vite)
│   ├── src/               # React components, contexts, and styles
│   │   └── tests/         # Vitest component unit tests
│   ├── e2e/               # Playwright E2E test specs (13 full test workflows)
│   └── dist/              # Compiled production distribution assets
├── requirements.txt       # Python dependencies (FastMCP 2.0, FastAPI, Qdrant, FastEmbed)
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
    "notes-rag-sse": {
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
    "notes-rag-http": {
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
- `notes://catalog/summary`

### Available MCP Prompts:
- `search_infrastructure_docs(topic="docker-compose network topology")`
- `find_implementation_symbol(symbol="execute_hybrid_search")`
