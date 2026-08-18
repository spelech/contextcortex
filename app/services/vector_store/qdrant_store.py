import os
import uuid
import logging
from typing import List, Dict, Any, Optional, Tuple, Union
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from app.services.vector_store.base import VectorStore, VectorDocument, VectorSearchResult
from app.services.embeddings import get_dense_embedding, get_sparse_embedding, get_dense_dim

logger = logging.getLogger("knowledge-rag-mcp.vector_store.qdrant")


class QdrantVectorStore(VectorStore):
    """Qdrant vector store backend supporting embedded disk, in-memory, and remote server modes with automatic fallback."""

    def __init__(
        self,
        url: Optional[str] = None,
        storage_path: Optional[str] = None,
        collection_name: Optional[str] = None,
        prefer_remote: Optional[bool] = None,
        timeout: float = 5.0,
        client: Optional[QdrantClient] = None,
        auto_init: bool = True,
    ):
        self.collection_name = collection_name or os.getenv("COLLECTION_NAME", "knowledge_rag_v1")
        self.timeout = timeout

        url_env = os.getenv("QDRANT_URL", "http://qdrant:6333")
        storage_path_env = os.getenv("QDRANT_STORAGE_PATH", "/app/data/qdrant_storage")

        if prefer_remote is None:
            prefer_remote = os.getenv("QDRANT_PREFER_REMOTE", "true").lower() in ("true", "1", "yes")

        if client is not None:
            self.client = client
            self.mode = "custom"
            self.location = "injected_client"
        elif prefer_remote and (storage_path is None or url is not None):
            target_url = url or url_env
            target_storage = storage_path or storage_path_env
            try:
                remote_client = QdrantClient(url=target_url, timeout=self.timeout, check_compatibility=False)
                remote_client.get_collections()
                self.client = remote_client
                self.mode = "remote"
                self.location = target_url
                logger.info(f"Connected to remote Qdrant server at {target_url}")
            except Exception as e:
                logger.warning(
                    f"Failed to connect to remote Qdrant at {target_url}: {e}. "
                    f"Falling back to embedded disk storage at {target_storage}"
                )
                if target_storage == ":memory:":
                    self.client = QdrantClient(location=":memory:")
                    self.mode = "memory"
                else:
                    os.makedirs(target_storage, exist_ok=True)
                    self.client = QdrantClient(path=target_storage)
                    self.mode = "embedded"
                self.location = target_storage
        else:
            target_storage = storage_path or storage_path_env
            if target_storage == ":memory:":
                self.client = QdrantClient(location=":memory:")
                self.mode = "memory"
            else:
                os.makedirs(target_storage, exist_ok=True)
                self.client = QdrantClient(path=target_storage)
                self.mode = "embedded"
            self.location = target_storage
            logger.info(f"Initialized embedded Qdrant client at {self.location}")

        if auto_init:
            self.ensure_collection()

    def ensure_collection(self) -> bool:
        """Initializes or validates named multi-vector (Dense + Sparse) Qdrant collection."""
        try:
            dim = get_dense_dim()
            if self.client.collection_exists(self.collection_name):
                info = self.client.get_collection(self.collection_name)
                vectors_config = info.config.params.vectors
                sparse_config = getattr(info.config.params, "sparse_vectors", None)

                needs_recreate = False
                if not isinstance(vectors_config, dict) or "dense" not in vectors_config:
                    logger.warning(
                        f"Existing collection '{self.collection_name}' uses legacy single-vector schema. "
                        f"Upgrading to Named Multi-Vectors (Dense + Sparse)..."
                    )
                    needs_recreate = True
                elif sparse_config is None or "sparse" not in sparse_config:
                    logger.warning(
                        f"Collection '{self.collection_name}' missing sparse vector index. "
                        f"Upgrading to Hybrid collection..."
                    )
                    needs_recreate = True
                elif hasattr(vectors_config.get("dense"), "size") and vectors_config["dense"].size != dim:
                    logger.warning(
                        f"Dense vector dimension mismatch in '{self.collection_name}': "
                        f"expected {dim}, found {vectors_config['dense'].size}. Recreating..."
                    )
                    needs_recreate = True

                if needs_recreate:
                    self.client.delete_collection(self.collection_name)

            if not self.client.collection_exists(self.collection_name):
                logger.info(f"Creating Hybrid Qdrant collection: {self.collection_name} (Dense: {dim}d, Sparse: BM25)")
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config={
                        "dense": qmodels.VectorParams(size=dim, distance=qmodels.Distance.COSINE)
                    },
                    sparse_vectors_config={
                        "sparse": qmodels.SparseVectorParams()
                    }
                )
                if self.mode == "remote":
                    for field in ["repo", "doc_type", "language", "path"]:
                        try:
                            self.client.create_payload_index(
                                collection_name=self.collection_name,
                                field_name=field,
                                field_schema=qmodels.PayloadSchemaType.KEYWORD
                            )
                        except Exception as ie:
                            logger.debug(f"Payload index creation for '{field}' info: {ie}")
            else:
                logger.info(f"Collection '{self.collection_name}' verified with Named Multi-Vectors.")
            return True
        except Exception as e:
            logger.error(f"Error initializing Qdrant collection '{self.collection_name}': {e}")
            return False

    def upsert_documents(
        self,
        documents: List[Union[VectorDocument, Dict[str, Any]]],
        batch_size: int = 100
    ) -> bool:
        """Upserts a batch of document chunks with vectors and payload."""
        if not documents:
            return True
        try:
            points = []
            for doc in documents:
                if isinstance(doc, dict):
                    doc_id = str(doc.get("id", uuid.uuid4()))
                    text = doc.get("text", doc.get("content", ""))
                    dense_vec = doc.get("dense_vector") or doc.get("dense")
                    sparse_indices = doc.get("sparse_indices")
                    sparse_values = doc.get("sparse_values")
                    sparse_vec = doc.get("sparse")
                    payload = doc.get("payload") if "payload" in doc else {
                        k: v for k, v in doc.items()
                        if k not in ("id", "text", "dense_vector", "sparse_indices", "sparse_values", "dense", "sparse")
                    }
                    if "content" not in payload and text:
                        payload["content"] = text
                else:
                    doc_id = str(doc.id)
                    text = doc.text
                    dense_vec = doc.dense_vector
                    sparse_indices = doc.sparse_indices
                    sparse_values = doc.sparse_values
                    sparse_vec = None
                    payload = doc.to_payload()

                try:
                    point_id = str(uuid.UUID(doc_id))
                except (ValueError, AttributeError):
                    point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, doc_id))

                if dense_vec is None and text:
                    dense_vec = get_dense_embedding(text)

                vectors: Dict[str, Any] = {}
                if dense_vec is not None:
                    vectors["dense"] = dense_vec

                if sparse_vec is not None:
                    if isinstance(sparse_vec, qmodels.SparseVector):
                        vectors["sparse"] = sparse_vec
                    elif isinstance(sparse_vec, dict):
                        vectors["sparse"] = qmodels.SparseVector(
                            indices=sparse_vec["indices"],
                            values=sparse_vec["values"]
                        )
                elif sparse_indices is not None and sparse_values is not None:
                    vectors["sparse"] = qmodels.SparseVector(
                        indices=sparse_indices,
                        values=sparse_values
                    )
                elif text:
                    s_vec = get_sparse_embedding(text)
                    if s_vec is not None:
                        vectors["sparse"] = s_vec

                points.append(qmodels.PointStruct(
                    id=point_id,
                    vector=vectors,
                    payload=payload
                ))

            effective_batch_size = max(1, batch_size)
            for i in range(0, len(points), effective_batch_size):
                chunk = points[i : i + effective_batch_size]
                self.client.upsert(
                    collection_name=self.collection_name,
                    points=chunk
                )
            return True
        except Exception as e:
            logger.error(f"Error upserting documents into Qdrant collection '{self.collection_name}': {e}")
            return False

    def delete_by_path(self, filepath: str) -> bool:
        """Purges vectors associated with a specific file path."""
        try:
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=qmodels.FilterSelector(
                    filter=qmodels.Filter(
                        must=[
                            qmodels.FieldCondition(
                                key="path",
                                match=qmodels.MatchValue(value=filepath)
                            )
                        ]
                    )
                )
            )
            return True
        except Exception as e:
            logger.error(f"Error deleting by path '{filepath}' in Qdrant: {e}")
            return False

    def delete_by_repo(self, repo_name: str) -> bool:
        """Purges all vectors belonging to a repository."""
        try:
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=qmodels.FilterSelector(
                    filter=qmodels.Filter(
                        must=[
                            qmodels.FieldCondition(
                                key="repo",
                                match=qmodels.MatchValue(value=repo_name)
                            )
                        ]
                    )
                )
            )
            return True
        except Exception as e:
            logger.error(f"Error deleting by repo '{repo_name}' in Qdrant: {e}")
            return False

    def search(
        self,
        query_text: str,
        doc_type: Optional[str] = None,
        repo: Optional[str] = None,
        language: Optional[str] = None,
        category: Optional[str] = None,
        tag: Optional[str] = None,
        limit: int = 5
    ) -> List[VectorSearchResult]:
        """Performs vector search returning ranked results using Dense + Sparse RRF."""
        if not query_text or not query_text.strip():
            return []

        try:
            if not self.client.collection_exists(self.collection_name):
                logger.warning(f"Collection '{self.collection_name}' does not exist in Qdrant.")
                return []

            dense_vec = get_dense_embedding(query_text.strip())
            sparse_vec = get_sparse_embedding(query_text.strip())

            must_conditions = []
            if doc_type:
                must_conditions.append(qmodels.FieldCondition(key="doc_type", match=qmodels.MatchValue(value=doc_type)))
            if repo:
                must_conditions.append(qmodels.FieldCondition(key="repo", match=qmodels.MatchValue(value=repo)))
            if language:
                must_conditions.append(qmodels.FieldCondition(key="language", match=qmodels.MatchValue(value=language)))
            if category:
                must_conditions.append(qmodels.FieldCondition(key="category", match=qmodels.MatchValue(value=category)))
            if tag:
                must_conditions.append(qmodels.FieldCondition(key="tags", match=qmodels.MatchAny(any=[tag])))

            query_filter = qmodels.Filter(must=must_conditions) if must_conditions else None

            if sparse_vec is not None and len(sparse_vec.indices) > 0:
                response = self.client.query_points(
                    collection_name=self.collection_name,
                    prefetch=[
                        qmodels.Prefetch(
                            query=dense_vec,
                            using="dense",
                            limit=limit * 2,
                            filter=query_filter
                        ),
                        qmodels.Prefetch(
                            query=sparse_vec,
                            using="sparse",
                            limit=limit * 2,
                            filter=query_filter
                        )
                    ],
                    query=qmodels.FusionQuery(fusion=qmodels.Fusion.RRF),
                    limit=limit
                )
            else:
                response = self.client.query_points(
                    collection_name=self.collection_name,
                    query=dense_vec,
                    using="dense",
                    query_filter=query_filter,
                    limit=limit
                )

            results: List[VectorSearchResult] = []
            for pt in response.points:
                results.append(
                    VectorSearchResult(
                        id=str(pt.id),
                        score=float(pt.score) if pt.score is not None else 0.0,
                        payload=pt.payload or {}
                    )
                )
            return results
        except Exception as e:
            logger.error(f"Error searching Qdrant collection '{self.collection_name}': {e}")
            return []

    def get_stats(self) -> Dict[str, Any]:
        """Returns collection info including point count, backend, and mode."""
        try:
            if not self.client.collection_exists(self.collection_name):
                return {
                    "backend": "qdrant",
                    "mode": self.mode,
                    "collection_name": self.collection_name,
                    "exists": False,
                    "points_count": 0,
                    "status": "not_found",
                    "location": self.location,
                }
            info = self.client.get_collection(self.collection_name)
            points_count = info.points_count or 0
            vectors_count = getattr(info, "vectors_count", points_count)
            return {
                "backend": "qdrant",
                "mode": self.mode,
                "collection_name": self.collection_name,
                "exists": True,
                "points_count": points_count,
                "vectors_count": vectors_count,
                "status": str(info.status),
                "location": self.location,
            }
        except Exception as e:
            logger.error(f"Error getting stats for Qdrant collection '{self.collection_name}': {e}")
            return {
                "backend": "qdrant",
                "mode": self.mode,
                "collection_name": self.collection_name,
                "exists": False,
                "error": str(e),
                "location": self.location,
            }

    def health_check(self) -> Tuple[bool, str]:
        """Validates connection and readiness of the backend."""
        try:
            self.client.get_collections()
            exists = self.client.collection_exists(self.collection_name)
            return True, f"Qdrant ({self.mode} @ {self.location}) is healthy; collection '{self.collection_name}' exists: {exists}"
        except Exception as e:
            return False, f"Qdrant ({self.mode}) health check failed: {e}"

    def close(self):
        """Cleanly close Qdrant client connection and release local storage lock."""
        try:
            if hasattr(self, "client") and self.client is not None:
                self.client.close()
        except Exception as e:
            logger.debug(f"Error closing Qdrant client: {e}")

