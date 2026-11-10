"""Vector store abstraction and backends."""

from app.services.vector_store.base import (
    VectorStore,
    VectorDocument,
    VectorSearchResult,
)
try:
    from app.services.vector_store.qdrant_store import (
        QdrantVectorStore,
    )
except ImportError:
    QdrantVectorStore = None  # type: ignore

try:
    from app.services.vector_store.chroma_store import (
        ChromaVectorStore,
    )
except ImportError:
    ChromaVectorStore = None  # type: ignore

from app.services.vector_store.pgvector_store import (
    PgVectorStore,
)
from app.services.vector_store.manager import (
    VectorStoreManager,
    get_vector_store,
    get_vector_store_config,
    switch_vector_store,
    test_vector_store_connection,
)

__all__ = [
    "VectorStore",
    "VectorDocument",
    "VectorSearchResult",
    "QdrantVectorStore",
    "ChromaVectorStore",
    "PgVectorStore",
    "VectorStoreManager",
    "get_vector_store",
    "get_vector_store_config",
    "switch_vector_store",
    "test_vector_store_connection",
]


