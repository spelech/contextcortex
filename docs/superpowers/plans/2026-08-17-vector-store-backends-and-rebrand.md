# Vector Store Multi-Backend (ChromaDB & Embedded/Remote Qdrant) and Knowledge RAG Rebrand Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide zero-configuration local-disk vector storage out of the box with embedded Qdrant and ChromaDB, support remote instances, enable dynamic UI/API provider switching with re-indexing, and rebrand the entire repository to `knowledge-rag-mcp`.

**Architecture:** Create an abstract `VectorStore` adapter interface under `app/services/vector_store/` with concrete implementations for `QdrantVectorStore` (embedded disk & remote server) and `ChromaVectorStore` (persistent disk & HTTP). Manage active instances and settings via `VectorStoreManager` backed by SQLite `system_metadata` (seeded from environment variables). Re-index on provider switch without lossy vector translation. Rebrand all loggers, collection defaults, namespaces, UI titles, and documentation to `knowledge-rag-mcp`.

**Tech Stack:** Python 3.12, FastMCP 2.0, FastAPI, Qdrant Client (embedded & remote), ChromaDB (`chromadb`), FastEmbed, SQLite WAL mode, pytest.

## Global Constraints
- Python version >= 3.10
- All tests in `tests/` must pass with `pytest`
- Embedded local disk mode must be the zero-config default without requiring external Docker services
- Maintain existing hybrid Dense (384d `BAAI/bge-small-en-v1.5`) + Sparse BM25 RRF search in Qdrant
- Provide metadata filtering and clean document storage in ChromaDB
- No breaking changes to MCP tool interfaces (`search_docs`, `find_symbol`, `get_index_status`, `list_indexed_files`, `get_file_summary`)
- Work must stay on `feature/vector-store-options` branch until explicitly told to merge

---

### Task 1: Scaffolding and Dependencies
**Files:**
- Modify: `requirements.txt`
- Create: `app/services/vector_store/__init__.py`

**Interfaces:**
- Produces: Package `app.services.vector_store` and `chromadb` requirement

- [ ] **Step 1: Update requirements.txt to include chromadb**
Add `chromadb>=0.5.0` to `requirements.txt`.

- [ ] **Step 2: Create vector_store package folder and __init__.py**
Create `app/services/vector_store/__init__.py`.

- [ ] **Step 3: Commit Task 1**
```bash
git add requirements.txt app/services/vector_store/__init__.py
git commit -m "chore: add chromadb dependency and create vector_store package"
```

---

### Task 2: Vector Store Base Interface & Models
**Files:**
- Create: `app/services/vector_store/base.py`
- Test: `tests/backend/test_vector_store_base.py`

**Interfaces:**
- Produces: `VectorStore` abstract class, `VectorDocument` dataclass/model, `VectorSearchResult` dataclass/model.

- [ ] **Step 1: Write unit tests for VectorStore base classes**
Test abstract enforcement and data class validation.

- [ ] **Step 2: Run test to verify failure**
Run: `pytest tests/backend/test_vector_store_base.py`

- [ ] **Step 3: Implement app/services/vector_store/base.py**
Implement `VectorStore` ABC with methods: `ensure_collection()`, `upsert_documents()`, `delete_by_path()`, `delete_by_repo()`, `search()`, `get_stats()`, `health_check()`.

- [ ] **Step 4: Run test to verify it passes**
Run: `pytest tests/backend/test_backend/test_vector_store_base.py`

- [ ] **Step 5: Commit Task 2**
```bash
git add app/services/vector_store/base.py tests/backend/test_vector_store_base.py
git commit -m "feat: add VectorStore base interface and models"
```

---

### Task 3: Qdrant Vector Store Implementation (Embedded & Remote)
**Files:**
- Create: `app/services/vector_store/qdrant_store.py`
- Test: `tests/backend/test_vector_store_qdrant.py`

**Interfaces:**
- Consumes: `VectorStore`, `get_dense_embedding`, `get_sparse_embedding`, `get_dense_dim`
- Produces: `QdrantVectorStore` class

- [ ] **Step 1: Write comprehensive unit tests for QdrantVectorStore**
Test embedded disk initialization (`storage_path`), remote initialization, named multi-vectors, upserting documents, deleting by path/repo, hybrid search with RRF, and automatic fallback from failed remote URL to embedded local disk.

- [ ] **Step 2: Run test to verify failure**
Run: `pytest tests/backend/test_vector_store_qdrant.py`

- [ ] **Step 3: Implement QdrantVectorStore in app/services/vector_store/qdrant_store.py**
Implement embedded client `QdrantClient(path=...)` and remote `QdrantClient(url=...)` with fallback logic, collection schema auto-healing, and point indexing.

- [ ] **Step 4: Run test to verify it passes**
Run: `pytest tests/backend/test_vector_store_qdrant.py`

- [ ] **Step 5: Commit Task 3**
```bash
git add app/services/vector_store/qdrant_store.py tests/backend/test_vector_store_qdrant.py
git commit -m "feat: implement QdrantVectorStore with embedded disk and remote support"
```

---

### Task 4: ChromaDB Vector Store Implementation (Persistent & Remote)
**Files:**
- Create: `app/services/vector_store/chroma_store.py`
- Test: `tests/backend/test_vector_store_chroma.py`

**Interfaces:**
- Consumes: `VectorStore`, `get_dense_embedding`
- Produces: `ChromaVectorStore` class

- [ ] **Step 1: Write unit tests for ChromaVectorStore**
Test persistent local disk storage initialization (`chromadb.PersistentClient`), upserting documents with metadata dictionary, deleting by path and repo, query filtering (by repo, doc_type, language, category), and stats.

- [ ] **Step 2: Run test to verify failure**
Run: `pytest tests/backend/test_vector_store_chroma.py`

- [ ] **Step 3: Implement ChromaVectorStore in app/services/vector_store/chroma_store.py**
Implement collection creation, dense embedding upserting, metadata serialization, `where` filter generation, and querying.

- [ ] **Step 4: Run test to verify it passes**
Run: `pytest tests/backend/test_vector_store_chroma.py`

- [ ] **Step 5: Commit Task 4**
```bash
git add app/services/vector_store/chroma_store.py tests/backend/test_vector_store_chroma.py
git commit -m "feat: implement ChromaVectorStore with persistent disk and HTTP support"
```

---

### Task 5: Vector Store Manager & Settings Seeding
**Files:**
- Create: `app/services/vector_store/manager.py`
- Modify: `app/services/db.py`
- Test: `tests/backend/test_vector_store_manager.py`

**Interfaces:**
- Consumes: `system_metadata` from `db.py`, `QdrantVectorStore`, `ChromaVectorStore`
- Produces: `get_vector_store()`, `get_vector_store_config()`, `switch_vector_store()`

- [ ] **Step 1: Write unit tests for VectorStoreManager**
Test default embedded initialization, env var seeding (`VECTOR_STORE`, `QDRANT_URL`, etc.), dynamic switching of provider/mode, and validation.

- [ ] **Step 2: Run test to verify failure**
Run: `pytest tests/backend/test_vector_store_manager.py`

- [ ] **Step 3: Implement VectorStoreManager and seed DB settings**
Implement singleton manager and DB helper methods in `app/services/vector_store/manager.py` and `app/services/db.py`.

- [ ] **Step 4: Run test to verify it passes**
Run: `pytest tests/backend/test_vector_store_manager.py`

- [ ] **Step 5: Commit Task 5**
```bash
git add app/services/vector_store/manager.py app/services/db.py tests/backend/test_vector_store_manager.py
git commit -m "feat: implement VectorStoreManager with dynamic switching and DB config seeding"
```

---

### Task 6: Integrate VectorStore with Indexer & Search Engine
**Files:**
- Modify: `app/services/indexer.py`
- Modify: `app/services/search.py`
- Test: `tests/backend/test_indexer_and_embeddings.py`, `tests/backend/test_search.py`

**Interfaces:**
- Consumes: `get_vector_store()` from `app.services.vector_store.manager`
- Produces: Decoupled indexing and search pipelines

- [ ] **Step 1: Update test fixtures for indexer and search**
Ensure mocks and tests use `get_vector_store()`.

- [ ] **Step 2: Refactor app/services/indexer.py**
Replace direct `qdrant` client calls with `get_vector_store()`.

- [ ] **Step 3: Refactor app/services/search.py**
Replace direct `qdrant.query_points` with `get_vector_store().search(...)`.

- [ ] **Step 4: Run indexer, search, and pipeline tests**
Run: `pytest tests/backend/test_indexer_and_embeddings.py tests/backend/test_search.py test_rag_pipeline.py`

- [ ] **Step 5: Commit Task 6**
```bash
git add app/services/indexer.py app/services/search.py tests/backend/test_indexer_and_embeddings.py tests/backend/test_search.py
git commit -m "refactor: integrate indexer and search services with VectorStoreManager"
```

---

### Task 7: REST API & MCP Tools for Vector Store Management
**Files:**
- Modify: `app/api/routes.py`
- Modify: `app/mcp/tools.py`
- Create: `tests/backend/test_api_vector_store.py`

**Interfaces:**
- Produces: `GET /admin/api/vector-store`, `POST /admin/api/vector-store/test`, `POST /admin/api/vector-store/switch`, updated `handle_index_status()`

- [ ] **Step 1: Write API tests for vector store management**
Test GET config, test connection POST, switch provider POST, and MCP index status.

- [ ] **Step 2: Run test to verify failure**
Run: `pytest tests/backend/test_api_vector_store.py`

- [ ] **Step 3: Implement API endpoints in app/api/routes.py and MCP tool updates**
Add vector store routes and update `app/mcp/tools.py`.

- [ ] **Step 4: Run test to verify it passes**
Run: `pytest tests/backend/test_api_vector_store.py`

- [ ] **Step 5: Commit Task 7**
```bash
git add app/api/routes.py app/mcp/tools.py tests/backend/test_api_vector_store.py
git commit -m "feat: add vector store configuration REST API endpoints and MCP status update"
```

---

### Task 8: Admin Web UI Vector Store Configuration Panel
**Files:**
- Modify: `frontend/index.html` (or `www/index.html`)
- Modify: `www/app.js`

- [ ] **Step 1: Add Vector Store Settings section to Web UI**
Add vector DB provider selector (Qdrant Embedded, Qdrant Remote, ChromaDB Persistent, ChromaDB Remote), storage path / URL input fields, "Test Connection" button, and "Save & Re-Index" action.

- [ ] **Step 2: Add Javascript handlers in www/app.js**
Fetch current vector store configuration on load, handle connection test with visual badges, and execute switch & re-index.

- [ ] **Step 3: Verify static files and API integration tests**
Run: `pytest tests/backend/test_api_routes.py`

- [ ] **Step 4: Commit Task 8**
```bash
git add frontend/ www/
git commit -m "feat: add vector store management controls to Admin Web UI"
```

---

### Task 9: Full Repository Rebrand to `knowledge-rag-mcp`
**Files:**
- Modify: `main.py`
- Modify: `app/services/logger.py`, `app/services/indexer.py`, `app/services/db.py`
- Modify: `README.md`, `ARCHITECTURE.md`, `DEVELOPER_DOCS.md`, `Dockerfile`, `extract_services.py`
- Modify: `frontend/` & `www/` titles and headers
- Modify: All tests mentioning `notes-rag-mcp`

- [ ] **Step 1: Update loggers, server titles, UUID namespace, and collection defaults**
Change server name to `knowledge-rag-mcp`, logger names to `knowledge-rag-mcp.*`, UUID namespace to `knowledge-rag-mcp.lan`, default collection to `knowledge_rag_v1`.

- [ ] **Step 2: Update documentation and Docker configurations**
Update `README.md`, `ARCHITECTURE.md`, `DEVELOPER_DOCS.md`, `Dockerfile` to reflect `knowledge-rag-mcp` and multi-backend storage options.

- [ ] **Step 3: Run all backend tests to ensure zero regressions**
Run: `pytest`

- [ ] **Step 4: Commit Task 9**
```bash
git add -A
git commit -m "refactor: complete repository rebranding to knowledge-rag-mcp"
```

---

### Task 10: End-to-End Verification & Walkthrough
**Files:**
- Verification only

- [ ] **Step 1: Run full test suite with coverage**
Run: `pytest --cov=app tests/`

- [ ] **Step 2: Test zero-config embedded boot**
Run standalone test verifying database boots without external services in embedded disk mode.

- [ ] **Step 3: Document completed work in walkthrough**
Create `walkthrough.md` in artifact directory.
