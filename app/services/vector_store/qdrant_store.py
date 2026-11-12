import logging
import os
import tempfile
import uuid
from typing import Any, Dict, List, Optional, Tuple, Union
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from app.services.embeddings import get_dense_dim, get_dense_embedding, get_sparse_embedding
from app.services.vector_store.base import VectorDocument, VectorSearchResult, VectorStore
from app.services.vector_store.qdrant_queries import (
    build_qdrant_filter,
    execute_qdrant_file_chunks,
    execute_qdrant_grep_chunks,
    execute_qdrant_search,
)

logger = logging.getLogger("contextcortex.vector_store.qdrant")


def get_default_qdrant_storage_path() -> str:
    env_path = os.getenv("QDRANT_STORAGE_PATH")
    if env_path:
        return env_path
    if os.path.exists("/app") and os.access("/app", os.W_OK):
        return "/app/data/qdrant_storage"
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "qdrant_storage")


def validate_qdrant_storage_path(target_storage: str) -> str:
    clean = os.path.normpath(os.path.abspath(target_storage))
    data_dir = os.path.abspath(os.getenv("DATA_DIR", "/app/data"))
    repo_data_dir = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"))
    allowed_roots = [data_dir, repo_data_dir, os.path.abspath(tempfile.gettempdir()), "/tmp"]
    for root in allowed_roots:
        if clean.startswith(root):
            return clean
    raise ValueError(f"Invalid Qdrant storage path outside authorized directories: {target_storage}")


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
        allow_fallback: Optional[bool] = None,
    ):
        self.collection_name = collection_name or os.getenv("COLLECTION_NAME", "knowledge_rag_v1")
        self.timeout = timeout

        url_env = os.getenv("QDRANT_URL", "http://qdrant:6333")
        storage_path_env = get_default_qdrant_storage_path()

        if prefer_remote is None:
            prefer_remote = os.getenv("QDRANT_PREFER_REMOTE", "true").lower() in ("true", "1", "yes")
        if allow_fallback is None:
            allow_fallback = os.getenv("QDRANT_ALLOW_FALLBACK", "false").lower() in ("true", "1", "yes")

        self.fallback_active = False
        self.fallback_reason = None

        if client is not None:
            self.client = client
            self.configured_mode = "custom"
            self.effective_mode = "custom"
            self.mode = "custom"
            self.location = "injected_client"
        elif prefer_remote and (storage_path is None or url is not None):
            self.configured_mode = "remote"
            target_url = url or url_env
            target_storage = storage_path or storage_path_env
            try:
                remote_client = QdrantClient(url=target_url, timeout=self.timeout, check_compatibility=False)
                remote_client.get_collections()
                self.client = remote_client
                self.mode = "remote"
                self.effective_mode = "remote"
                self.location = target_url
                logger.info(f"Connected to remote Qdrant server at {target_url}")
            except Exception as e:
                if not allow_fallback:
                    logger.error(f"Failed to connect to remote Qdrant at {target_url}: {e}")
                    raise ConnectionError(f"Failed to connect to remote Qdrant at {target_url}: {e}") from e

                self.fallback_active = True
                self.fallback_reason = str(e)
                logger.warning(
                    f"Failed to connect to remote Qdrant at {target_url}: {e}. "
                    f"Falling back to embedded disk storage at {target_storage} (opt-in fallback active)"
                )
                if target_storage == ":memory:":
                    self.client = QdrantClient(location=":memory:")
                    self.mode = "memory"
                    self.effective_mode = "memory"
                    self.location = target_storage
                else:
                    clean_storage = validate_qdrant_storage_path(target_storage)
                    os.makedirs(clean_storage, exist_ok=True)
                    self.client = QdrantClient(path=clean_storage)
                    self.mode = "embedded"
                    self.effective_mode = "embedded"
                    self.location = clean_storage
        else:
            target_storage = storage_path or storage_path_env
            if target_storage == ":memory:":
                self.client = QdrantClient(location=":memory:")
                self.configured_mode = "memory"
                self.effective_mode = "memory"
                self.mode = "memory"
                self.location = target_storage
            else:
                clean_storage = validate_qdrant_storage_path(target_storage)
                os.makedirs(clean_storage, exist_ok=True)
                self.client = QdrantClient(path=clean_storage)
                self.configured_mode = "embedded"
                self.effective_mode = "embedded"
                self.mode = "embedded"
                self.location = clean_storage
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
                    logger.warning(f"Existing collection '{self.collection_name}' uses legacy single-vector schema. Upgrading...")
                    needs_recreate = True
                elif sparse_config is None or "sparse" not in sparse_config:
                    logger.warning(f"Collection '{self.collection_name}' missing sparse vector index. Upgrading...")
                    needs_recreate = True
                elif hasattr(vectors_config.get("dense"), "size") and vectors_config["dense"].size != dim:
                    logger.warning(
                        f"Dense vector dimension mismatch in '{self.collection_name}': expected {dim}, found {vectors_config['dense'].size}. Recreating..."
                    )
                    needs_recreate = True

                if needs_recreate:
                    self.client.delete_collection(self.collection_name)
                    try:
                        from app.services.database import clear_indexing_metadata
                        clear_indexing_metadata()
                    except Exception as cm_err:
                        logger.warning(f"Failed to clear indexing metadata during collection recreation: {cm_err}")

            if not self.client.collection_exists(self.collection_name):
                logger.info(f"Creating Hybrid Qdrant collection: {self.collection_name} (Dense: {dim}d, Sparse: BM25)")
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config={"dense": qmodels.VectorParams(size=dim, distance=qmodels.Distance.COSINE)},
                    sparse_vectors_config={"sparse": qmodels.SparseVectorParams()},
                )
                if self.mode == "remote":
                    for field in ["repo", "doc_type", "language", "path"]:
                        try:
                            self.client.create_payload_index(
                                collection_name=self.collection_name,
                                field_name=field,
                                field_schema=qmodels.PayloadSchemaType.KEYWORD,
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
        batch_size: int = 100,
    ) -> bool:
        """Upserts a batch of document chunks with vectors and payload."""
        if not documents:
            return True
        try:
            expected_dim: Optional[int] = None
            try:
                if self.client.collection_exists(self.collection_name):
                    info = self.client.get_collection(self.collection_name)
                    v_cfg = getattr(info.config.params, "vectors", None)
                    if isinstance(v_cfg, dict) and "dense" in v_cfg:
                        expected_dim = getattr(v_cfg["dense"], "size", None)
            except Exception:
                expected_dim = None

            points = []
            for doc in documents:
                if isinstance(doc, dict):
                    doc_id = str(doc.get("id", uuid.uuid4()))
                    text = doc.get("text", doc.get("content", ""))
                    dense_vec = doc.get("dense_vector") or doc.get("dense")
                    sparse_indices = doc.get("sparse_indices")
                    sparse_values = doc.get("sparse_values")
                    sparse_vec = doc.get("sparse")
                    payload = dict(doc.get("payload")) if "payload" in doc and isinstance(doc.get("payload"), dict) else {
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

                if isinstance(text, str):
                    text = text.replace("\x00", "")
                for pk in ("path", "rel_path", "filepath", "folder", "permalink_url", "github_url"):
                    if isinstance(payload.get(pk), str):
                        payload[pk] = payload[pk].replace("\x00", "").replace("\\", "/")

                try:
                    point_id = str(uuid.UUID(doc_id))
                except (ValueError, AttributeError):
                    point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, doc_id))

                if dense_vec is None and text:
                    dense_vec = get_dense_embedding(text)

                if dense_vec is not None and expected_dim is not None and len(dense_vec) != expected_dim:
                    raise ValueError(
                        f"could not broadcast input array from shape ({len(dense_vec)},) into shape ({expected_dim},)"
                    )

                vectors: Dict[str, Any] = {}
                if dense_vec is not None:
                    vectors["dense"] = dense_vec

                if sparse_vec is not None:
                    if isinstance(sparse_vec, qmodels.SparseVector):
                        vectors["sparse"] = sparse_vec
                    elif isinstance(sparse_vec, dict):
                        vectors["sparse"] = qmodels.SparseVector(indices=sparse_vec["indices"], values=sparse_vec["values"])
                elif sparse_indices is not None and sparse_values is not None:
                    vectors["sparse"] = qmodels.SparseVector(indices=sparse_indices, values=sparse_values)
                elif text:
                    s_vec = get_sparse_embedding(text)
                    if s_vec is not None:
                        vectors["sparse"] = s_vec

                points.append(qmodels.PointStruct(id=point_id, vector=vectors, payload=payload))

            effective_batch_size = max(1, batch_size)
            for i in range(0, len(points), effective_batch_size):
                self.client.upsert(collection_name=self.collection_name, points=points[i : i + effective_batch_size])
            return True
        except Exception as e:
            logger.error(f"Error upserting documents into Qdrant collection '{self.collection_name}': {e}")
            return False

    def delete_by_path(self, filepath: str) -> bool:
        """Purges vectors associated with a specific file path."""
        norm_fp = (filepath or "").replace("\\", "/")
        conds = [qmodels.FieldCondition(key="path", match=qmodels.MatchValue(value=filepath))]
        if norm_fp != filepath:
            conds.append(qmodels.FieldCondition(key="path", match=qmodels.MatchValue(value=norm_fp)))
        filt = qmodels.Filter(must=conds) if len(conds) == 1 else qmodels.Filter(should=conds)
        try:
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=qmodels.FilterSelector(filter=filt),
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
                        must=[qmodels.FieldCondition(key="repo", match=qmodels.MatchValue(value=repo_name))]
                    )
                ),
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
        limit: int = 5,
        dense_weight: Optional[float] = None,
        search_mode: str = "hybrid",
    ) -> List[VectorSearchResult]:
        supported = self.get_capabilities().get("search_modes", ["hybrid", "semantic", "lexical"])
        return execute_qdrant_search(
            client=self.client,
            collection_name=self.collection_name,
            supported_modes=supported,
            dense_embed_fn=get_dense_embedding,
            sparse_embed_fn=get_sparse_embedding,
            query_text=query_text,
            doc_type=doc_type,
            repo=repo,
            language=language,
            category=category,
            tag=tag,
            limit=limit,
            dense_weight=dense_weight,
            search_mode=search_mode,
        )

    def get_capabilities(self) -> Dict[str, Any]:
        return {"search_modes": ["hybrid", "semantic", "lexical"], "supports_weighting": True}

    def get_stats(self) -> Dict[str, Any]:
        base_stats: Dict[str, Any] = {
            "backend": "qdrant",
            "mode": self.mode,
            "configured_mode": getattr(self, "configured_mode", self.mode),
            "effective_mode": getattr(self, "effective_mode", self.mode),
            "fallback_active": getattr(self, "fallback_active", False),
            "fallback_reason": getattr(self, "fallback_reason", None),
            "collection_name": self.collection_name,
            "location": self.location,
        }
        try:
            if not self.client.collection_exists(self.collection_name):
                base_stats.update({
                    "exists": False, "points_count": 0, "status": "not_found",
                    "capabilities": self.get_capabilities(),
                })
                return base_stats
            info = self.client.get_collection(self.collection_name)
            points_count = info.points_count or 0
            base_stats.update({
                "exists": True, "points_count": points_count,
                "vectors_count": getattr(info, "vectors_count", points_count),
                "status": str(info.status),
                "capabilities": self.get_capabilities(),
            })
            return base_stats
        except Exception as e:
            logger.error(f"Error getting stats for Qdrant collection '{self.collection_name}': {e}")
            base_stats.update({
                "exists": False, "error": "Failed to retrieve Qdrant statistics.",
                "capabilities": self.get_capabilities(),
            })
            return base_stats

    def health_check(self) -> Tuple[bool, str]:
        try:
            self.client.get_collections()
            exists = self.client.collection_exists(self.collection_name)
            fallback_note = (
                f" [DEGRADED: Fallback to {self.effective_mode} from {self.configured_mode} active; reason: {self.fallback_reason}]"
                if getattr(self, "fallback_active", False)
                else ""
            )
            return True, f"Qdrant ({self.effective_mode} @ {self.location}) is healthy; collection '{self.collection_name}' exists: {exists}{fallback_note}"
        except Exception as e:
            logger.warning(f"Qdrant ({self.mode}) health check failed: {e}")
            return False, f"Qdrant ({self.mode}) health check failed."

    def get_file_chunks(self, path: str, repo: Optional[str] = None) -> List[Dict[str, Any]]:
        if not hasattr(self, "client") or not self.client:
            return []
        return execute_qdrant_file_chunks(client=self.client, collection_name=self.collection_name, path=path, repo=repo)

    def grep_chunks(
        self,
        pattern: str,
        repo: Optional[str] = None,
        path_glob: Optional[str] = None,
        is_regex: bool = False,
        case_sensitive: bool = False,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        if not hasattr(self, "client") or not self.client:
            return []
        return execute_qdrant_grep_chunks(
            client=self.client, collection_name=self.collection_name,
            pattern=pattern, repo=repo, path_glob=path_glob,
            is_regex=is_regex, case_sensitive=case_sensitive, limit=limit,
        )

    def close(self) -> None:
        try:
            if hasattr(self, "client") and self.client is not None:
                self.client.close()
        except Exception as e:
            logger.debug(f"Error closing Qdrant client: {e}")


__all__ = [
    "QdrantVectorStore",
    "get_default_qdrant_storage_path",
    "validate_qdrant_storage_path",
    "build_qdrant_filter",
]
