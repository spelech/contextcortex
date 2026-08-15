# Developer Documentation (v2.0.0)

This document provides instructions for developing, testing, and running the Notes & Code RAG MCP Server locally.

---

## 🛠️ Prerequisites
- **Python 3.11+**
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

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Start Qdrant Vector Database:**
   ```bash
   docker run -d --name qdrant -p 6333:6333 -p 6334:6334 \
       -v $(pwd)/qdrant_storage:/qdrant/storage \
       qdrant/qdrant:latest
   ```

5. **Set Environment Variables (Optional):**
   ```bash
   export QDRANT_URL="http://localhost:6333"
   export COLLECTION_NAME="notes_rag_v2"
   export EMBEDDING_PROVIDER="local"
   export GITHUB_TOKEN="ghp_your_token" # Optional: For higher rate limits & private repos
   ```

6. **Run the server:**
   ```bash
   python server.py
   ```
   The server starts on port `3000`, initializes SQLite tables, configures Qdrant named multi-vectors (Dense + BM25 Sparse), and serves `/admin/` and `/sse`.

---

## 🧪 Running Automated Tests

Run the test suite to verify AST parsing, embedding generation, ephemeral Git cloning, and database indexing:

```bash
python -m unittest test_rag_pipeline.py
```

---

## 📁 Project Architecture & Modules

```
notes-rag-mcp/
├── server.py              # Main FastAPI app, MCP tool definitions, and REST endpoints
├── chunker.py             # Tree-sitter AST parser (code) & Markdown header chunker (docs)
├── embeddings.py          # FastEmbed Dense (bge-small) & Sparse (BM25) multi-vector engine
├── git_manager.py         # Ephemeral shallow clone, commit SHA tracking, GitHub permalinks
├── db.py                  # SQLite database manager (WAL mode, repos, files, AST symbols)
├── test_rag_pipeline.py   # Unit & integration test suite
├── www/                   # Web Admin Dashboard
│   ├── index.html         # Tabbed dashboard layout (Overview, Git Repos, Search Tester)
│   ├── app.js             # Client-side state, live sync triggers, and search inspector
│   └── styles.css         # Modern glassmorphic dark-mode design system
├── requirements.txt       # Python dependencies
├── Dockerfile             # Container definition with Python 3.11 & Git
└── ARCHITECTURE.md        # Deep architectural design specification
```

---

## 🔍 Testing MCP Client Connections

Connect any MCP client supporting Server-Sent Events (SSE) to:
- **SSE Endpoint**: `http://localhost:3000/sse`
- **POST Message Relay**: `http://localhost:3000/messages/`

### Example MCP Client Configuration (`claude_desktop_config.json` / Cursor)
```json
{
  "mcpServers": {
    "notes-code-rag": {
      "url": "http://localhost:3000/sse"
    }
  }
}
```

### Available Tools to Test:
- `search_code(query="authentication middleware", repo="backend-api")`
- `search_docs(query="caddy reverse proxy ports")`
- `find_symbol(name="extract_symbols_and_chunks", exact=true)`
- `get_file_outline(filepath="chunker.py")`
- `list_repositories()`
- `sync_repository(repo="backend-api")`
- `index_status()`
