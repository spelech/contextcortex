# Design Specification: Vector Store Multi-Backend (ChromaDB & Embedded/Remote Qdrant) & Knowledge RAG Rebrand

**Date**: 2026-08-17  
**Branch**: `feature/vector-store-options`  
**Status**: Proposed / Under Review  

---

## 1. Overview & Problem Statement

Currently, `notes-rag-mcp` requires a standalone remote Qdrant container running on port 6333 (`QDRANT_URL=http://qdrant:6333`). For lightweight or single-container deployments, requiring a separate vector database service increases operational overhead and setup complexity.

Furthermore, the server has evolved from a simple notes RAG assistant to an intelligent multi-repository codebase and documentation retrieval system.

This design introduces:
1. **Zero-Configuration Local Disk Default**: By default, the server runs with embedded disk-based vector storage (`/app/data/vector_storage` or `./data/`), requiring no external Docker container.
2. **Multi-Backend Vector Store Abstraction**:
   - **Qdrant**: Embedded disk mode (`QdrantClient(path=...)`) & Remote server mode (`QdrantClient(url=...)`) with automatic fallback to embedded if remote is unreachable. Full Named Multi-Vectors (Dense + BM25 Sparse RRF).
   - **ChromaDB**: Persistent disk mode (`chromadb.PersistentClient(path=...)`) & Remote HTTP client (`chromadb.HttpClient(...)`). Dense similarity search with metadata filtering.
3. **Dynamic Provider Selection & Re-ingestion**:
   - Vector store configuration is stored in SQLite `system_metadata` (seeded from environment variables on startup).
   - Switching providers via UI or API triggers a clean re-ingestion (`run_full_indexing()`), preserving native database features without lossy cross-DB data migrations.
4. **Full Rebranding to `knowledge-rag-mcp`**:
   - Complete migration across codebase, loggers, MCP server metadata, FastMCP endpoints, Admin UI, and documentation from `notes-rag-mcp` to `knowledge-rag-mcp`.

---

## 2. Architecture & Components

```mermaid
graph TD
    subgraph FastAPI & FastMCP Server ["knowledge-rag-mcp Server"]
        MCPTools["MCP Tools (/sse, /mcp)"]
        AdminAPI["Admin REST API (/admin/api/*)"]
        AdminUI["Admin Web UI (/admin/*)"]
        Indexer["Indexer Engine"]
        Search["Search Engine"]
    end

    subgraph Config & State
        SQLite["SQLite DB (index_cache.db)<br/>- system_metadata<br/>- indexed_files<br/>- ast_symbols<br/>- file_summaries<br/>- git_repositories"]
        EnvVars["Environment Variables<br/>(VECTOR_STORE, QDRANT_URL, etc.)"]
    end

    subgraph Vector Store Layer ["Vector Store Abstraction (app/services/vector_store/)"]
        VSManager["VectorStoreManager<br/>(get_vector_store, switch_backend)"]
        VSBase["VectorStore Interface"]
        QdrantStore["QdrantVectorStore<br/>- Embedded Disk (Default)<br/>- Remote HTTP Server<br/>- Dense + FastEmbed BM25 RRF"]
        ChromaStore["ChromaVectorStore<br/>- Persistent Disk<br/>- Remote HTTP Server<br/>- Dense + Metadata Filtering"]
    end

    subgraph Physical Storage
        DiskQdrant["/app/data/qdrant_storage (Disk)"]
        DiskChroma["/app/data/chroma_storage (Disk)"]
        RemoteQdrant["External Qdrant Server (6333)"]
        RemoteChroma["External Chroma Server (8000)"]
    end

    EnvVars -->|Seed on Boot| SQLite
    SQLite -->|Load Config| VSManager
    VSManager --> VSBase
    VSBase <|-- QdrantStore
    VSBase <|-- ChromaStore

    QdrantStore --> DiskQdrant
    QdrantStore -.-> RemoteQdrant
    ChromaStore --> DiskChroma
    ChromaStore -.-> RemoteChroma

    Indexer --> VSManager
    Search --> VSManager
    AdminAPI --> VSManager
    AdminAPI --> SQLite
```

---

## 3. Detailed Component Specifications

### 3.1 Vector Store Abstraction Interface (`app/services/vector_store/base.py`)
```python
class VectorStore(ABC):
    @abstractmethod
    def ensure_collection(self) -> bool:
        """Creates or validates vector collection schema."""
        pass

    @abstractmethod
    def upsert_documents(self, documents: List[Dict[str, Any]]) -> bool:
        """Upserts a batch of document chunks with vectors and payload."""
        pass

    @abstractmethod
    def delete_by_path(self, filepath: str) -> bool:
        """Purges vectors associated with a specific file path."""
        pass

    @abstractmethod
    def delete_by_repo(self, repo_name: str) -> bool:
        """Purges all vectors belonging to a repository."""
        pass

    @abstractmethod
    def search(
        self,
        query_text: str,
        doc_type: Optional[str] = None,
        repo: Optional[str] = None,
        language: Optional[str] = None,
        category: Optional[str] = None,
        tag: Optional[str] = None,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Performs vector search returning ranked results."""
        pass

    @abstractmethod
    def get_stats(self) -> Dict[str, Any]:
        """Returns collection info including point count and mode."""
        pass

    @abstractmethod
    def health_check(self) -> Tuple[bool, str]:
        """Validates connection/readiness of the backend."""
        pass
```

### 3.2 Qdrant Implementation (`app/services/vector_store/qdrant_store.py`)
- **Embedded Mode**: Initializes `QdrantClient(path=storage_path)`.
- **Remote Mode**: Initializes `QdrantClient(url=url, timeout=5.0)`.
- **Auto-Fallback**: If remote initialization fails, logs a warning and automatically instantiates the embedded disk client at `storage_path`.
- **Features**: Dense (384d `BAAI/bge-small-en-v1.5`) + Sparse (`Qdrant/bm25`) with Reciprocal Rank Fusion (RRF). Payload indexes on `repo`, `doc_type`, `language`, `path`.

### 3.3 ChromaDB Implementation (`app/services/vector_store/chroma_store.py`)
- **Persistent Mode**: Initializes `chromadb.PersistentClient(path=storage_path)`.
- **Remote Mode**: Initializes `chromadb.HttpClient(host=host, port=port)`.
- **Features**: Dense vector embedding (384d) with metadata dictionary filtering on `repo`, `doc_type`, `language`, `path`, `category`, `tags`.
- Ingestion converts metadata fields to JSON/primitive strings compatible with Chroma's metadata constraints.

### 3.4 Vector Store Manager (`app/services/vector_store/manager.py`)
- Reads active settings from SQLite `system_metadata`.
- On boot, seeds SQLite with values from environment variables if not already saved:
  - `VECTOR_STORE` (default: `qdrant`)
  - `VECTOR_STORE_MODE` (default: `embedded` if no `QDRANT_URL`, or `remote` if `QDRANT_URL` is set)
  - `VECTOR_STORAGE_PATH` (default: `/app/data/vector_storage` or `./data/vector_storage`)
  - `QDRANT_URL` (default: `""`)
  - `CHROMA_URL` (default: `""`)
  - `COLLECTION_NAME` (default: `knowledge_rag_v1`)
- Provides `switch_vector_store(provider, mode, storage_path, url)` which reconfigures the manager, initializes the new backend, saves metadata, and triggers `run_full_indexing()`.

---

## 4. Rebranding Strategy (`knowledge-rag-mcp`)

1. **Package & Service Namespaces**:
   - Logger: `knowledge-rag-mcp` (subloggers `knowledge-rag-mcp.db`, `knowledge-rag-mcp.git`, etc.)
   - UUID Namespace: `knowledge-rag-mcp.lan`
   - Default Collection: `knowledge_rag_v1`
2. **MCP Tool & Prompt Metadata**:
   - Server Name: `knowledge-rag-mcp` / `Knowledge RAG MCP`
   - Dynamic catalog description: Unified Knowledge & Code Intelligence RAG.
3. **Web UI**:
   - Header, tab titles, favicon, and documentation rebranded to **Knowledge RAG Hub**.
4. **Documentation & Configs**:
   - `README.md`, `ARCHITECTURE.md`, `DEVELOPER_DOCS.md`, `Dockerfile`, `requirements.txt`.

---

## 5. Admin UI & REST API Enhancements

### New / Updated Endpoints in `app/api/routes.py`:
- `GET /admin/api/vector-store`: Returns active provider, mode, storage path, remote URL, collection stats, and health status.
- `POST /admin/api/vector-store/test`: Tests a potential vector store connection (URL or local path) without applying changes.
- `POST /admin/api/vector-store/switch`: Updates active configuration in `system_metadata`, instantiates the new store, and triggers a full background re-indexing.

### Admin UI Settings View:
- Live vector database card showing current backend (`Qdrant Embedded`, `Qdrant Remote`, `ChromaDB Persistent`, `ChromaDB Remote`).
- Form with quick-select options, URL/Path inputs, "Test Connection" button, and "Save & Re-Index" action.

---

## 6. Testing & Verification Strategy

1. **Unit Tests**:
   - `tests/backend/test_vector_store_qdrant.py`: Test embedded local disk Qdrant, points upsert, search, delete, and remote fallback.
   - `tests/backend/test_vector_store_chroma.py`: Test persistent disk ChromaDB, document upsert, search with metadata filters, delete.
   - `tests/backend/test_vector_store_manager.py`: Test manager initialization, env seeding, dynamic switching, and re-indexing hook.
2. **Integration & API Tests**:
   - `tests/backend/test_api_vector_store.py`: Test GET/POST vector store endpoints.
   - Update all existing test suites to use the new `VectorStore` adapter and `knowledge-rag-mcp` loggers/namespaces.
3. **End-to-End Test**:
   - Run full pytest suite across all 140+ existing tests + new vector store tests.
   - Verify server boots with zero external services using embedded disk storage out of the box.
