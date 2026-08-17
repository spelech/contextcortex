"""Vector store abstraction and backends."""

from app.services.vector_store.base import (
    VectorStore,
    VectorDocument,
    VectorSearchResult,
)

__all__ = [
    "VectorStore",
    "VectorDocument",
    "VectorSearchResult",
]
