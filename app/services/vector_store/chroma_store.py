import os
import json
import logging
import uuid
from typing import List, Dict, Any, Optional, Tuple, Union
from urllib.parse import urlparse
import chromadb


from app.services.vector_store.base import VectorStore, VectorDocument, VectorSearchResult
from app.services.embeddings import get_dense_embedding

logger = logging.getLogger("knowledge-rag-mcp.vector_store.chroma")


def _sanitize_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Sanitizes metadata dictionary to conform to ChromaDB constraints.

    ChromaDB allows strings, ints, floats, bools, and non-empty lists of primitives.
    None values, empty lists, and complex dicts are dropped or converted.
    """
    clean: Dict[str, Any] = {}
    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            clean[key] = value
        elif isinstance(value, list):
            if len(value) == 0:
                continue
            if all(isinstance(x, (str, int, float, bool)) for x in value):
                clean[key] = value
            else:
                clean[key] = [str(x) for x in value]
        elif isinstance(value, dict):
            clean[key] = json.dumps(value)
        else:
            clean[key] = str(value)
    return clean


def get_default_chroma_storage_path() -> str:
    env_path = os.getenv("CHROMA_STORAGE_PATH")
    if env_path:
        return env_path
    if os.path.exists("/app") and os.access("/app", os.W_OK):
        return "/app/data/chroma_storage"
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "chroma_storage")


class ChromaVectorStore(VectorStore):
    """ChromaDB vector store backend supporting persistent disk, in-memory, and remote HTTP modes with auto-fallback."""

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        ssl: Optional[bool] = None,
        headers: Optional[Dict[str, str]] = None,
        storage_path: Optional[str] = None,
        collection_name: Optional[str] = None,
        prefer_remote: Optional[bool] = None,
        url: Optional[str] = None,
        client: Optional[Any] = None,
        auto_init: bool = True,
    ):
        self.collection_name = collection_name or os.getenv("COLLECTION_NAME", "knowledge_rag_v1")
        self.collection = None

        if url:
            parsed = urlparse(url if "://" in url else f"http://{url}")
            host = parsed.hostname or host
            if parsed.port:
                port = parsed.port
            if parsed.scheme == "https":
                ssl = True
            if prefer_remote is None:
                prefer_remote = True

        target_host = host or os.getenv("CHROMA_HOST", "localhost")
        target_port = int(port or os.getenv("CHROMA_PORT", "8000"))
        target_ssl = ssl if ssl is not None else os.getenv("CHROMA_SSL", "false").lower() in ("true", "1", "yes")
        target_storage = storage_path or get_default_chroma_storage_path()


        if prefer_remote is None:
            prefer_remote = os.getenv("CHROMA_PREFER_REMOTE", "false").lower() in ("true", "1", "yes")
            if host is not None:
                prefer_remote = True

        if client is not None:
            self.client = client
            self.mode = "custom"
            self.location = "injected_client"
        elif prefer_remote:
            try:
                remote_client = chromadb.HttpClient(
                    host=target_host,
                    port=target_port,
                    ssl=target_ssl,
                    headers=headers,
                )
                remote_client.heartbeat()
                self.client = remote_client
                self.mode = "remote"
                self.location = f"{'https' if target_ssl else 'http'}://{target_host}:{target_port}"
                logger.info(f"Connected to remote Chroma server at {self.location}")
            except Exception as e:
                logger.warning(
                    f"Failed to connect to remote Chroma at {target_host}:{target_port}: {e}. "
                    f"Falling back to persistent disk storage at {target_storage}"
                )
                if target_storage == ":memory:":
                    self.client = chromadb.EphemeralClient()
                    self.mode = "memory"
                else:
                    os.makedirs(target_storage, exist_ok=True)
                    self.client = chromadb.PersistentClient(path=target_storage)
                    self.mode = "persistent"
                self.location = target_storage
        else:
            if target_storage == ":memory:":
                self.client = chromadb.EphemeralClient()
                self.mode = "memory"
            else:
                os.makedirs(target_storage, exist_ok=True)
                self.client = chromadb.PersistentClient(path=target_storage)
                self.mode = "persistent"
            self.location = target_storage
            logger.info(f"Initialized local Chroma client at {self.location}")

        if auto_init:
            self.ensure_collection()

    def ensure_collection(self) -> bool:
        """Initializes or retrieves the collection with cosine distance metric."""
        try:
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"}
            )
            logger.info(f"Chroma collection '{self.collection_name}' ready.")
            return True
        except Exception as e:
            logger.error(f"Error initializing Chroma collection '{self.collection_name}': {e}")
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
            if self.collection is None:
                if not self.ensure_collection():
                    return False

            ids: List[str] = []
            embeddings: List[List[float]] = []
            documents_text: List[str] = []
            metadatas: List[Dict[str, Any]] = []

            for doc in documents:
                if isinstance(doc, dict):
                    doc_id = str(doc.get("id") or uuid.uuid4())
                    text = str(doc.get("text") or doc.get("content") or "")
                    dense_vec = doc.get("dense_vector") or doc.get("dense")
                    raw_payload = doc.get("payload") if "payload" in doc else {
                        k: v for k, v in doc.items()
                        if k not in ("id", "text", "dense_vector", "dense", "sparse_indices", "sparse_values", "sparse")
                    }
                    if "content" not in raw_payload and text:
                        raw_payload["content"] = text
                else:
                    doc_id = str(doc.id)
                    text = doc.text
                    dense_vec = doc.dense_vector
                    raw_payload = doc.to_payload()

                if dense_vec is None and text:
                    dense_vec = get_dense_embedding(text)

                clean_metadata = _sanitize_metadata(raw_payload)

                ids.append(doc_id)
                embeddings.append(dense_vec if dense_vec is not None else [0.0] * 384)
                documents_text.append(text)
                metadatas.append(clean_metadata)

            effective_batch_size = max(1, batch_size)
            for i in range(0, len(ids), effective_batch_size):
                self.collection.upsert(
                    ids=ids[i : i + effective_batch_size],
                    embeddings=embeddings[i : i + effective_batch_size],
                    documents=documents_text[i : i + effective_batch_size],
                    metadatas=metadatas[i : i + effective_batch_size],
                )
            return True
        except Exception as e:
            logger.error(f"Error upserting documents into Chroma collection '{self.collection_name}': {e}")
            return False

    def delete_by_path(self, filepath: str) -> bool:
        """Purges vectors associated with a specific file path."""
        try:
            if self.collection is None:
                if not self.ensure_collection():
                    return False
            self.collection.delete(where={"path": filepath})
            return True
        except Exception as e:
            logger.error(f"Error deleting by path '{filepath}' in Chroma: {e}")
            return False

    def delete_by_repo(self, repo_name: str) -> bool:
        """Purges all vectors belonging to a repository."""
        try:
            if self.collection is None:
                if not self.ensure_collection():
                    return False
            self.collection.delete(where={"repo": repo_name})
            return True
        except Exception as e:
            logger.error(f"Error deleting by repo '{repo_name}' in Chroma: {e}")
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
        """Performs dense vector search returning ranked results."""
        if not query_text or not query_text.strip():
            return []

        try:
            if self.collection is None:
                if not self.ensure_collection():
                    return []

            dense_vec = get_dense_embedding(query_text.strip())

            conditions: List[Dict[str, Any]] = []
            if doc_type:
                conditions.append({"doc_type": doc_type})
            if repo:
                conditions.append({"repo": repo})
            if language:
                conditions.append({"language": language})
            if category:
                conditions.append({"category": category})
            if tag:
                conditions.append({"tags": {"$contains": tag}})

            where_filter = None
            if len(conditions) == 1:
                where_filter = conditions[0]
            elif len(conditions) > 1:
                where_filter = {"$and": conditions}

            query_kwargs: Dict[str, Any] = {
                "query_embeddings": [dense_vec],
                "n_results": limit,
            }
            if where_filter:
                query_kwargs["where"] = where_filter

            response = self.collection.query(**query_kwargs)

            results: List[VectorSearchResult] = []
            if response and response.get("ids") and len(response["ids"]) > 0:
                ids_list = response["ids"][0]
                distances = response.get("distances", [[]])[0] if response.get("distances") else []
                metadatas = response.get("metadatas", [[]])[0] if response.get("metadatas") else []
                documents = response.get("documents", [[]])[0] if response.get("documents") else []

                for i, doc_id in enumerate(ids_list):
                    dist = distances[i] if i < len(distances) and distances[i] is not None else 0.0
                    score = float(max(0.0, 1.0 - dist))
                    payload = dict(metadatas[i]) if i < len(metadatas) and metadatas[i] is not None else {}
                    if "content" not in payload and i < len(documents) and documents[i]:
                        payload["content"] = documents[i]

                    results.append(
                        VectorSearchResult(
                            id=str(doc_id),
                            score=score,
                            payload=payload
                        )
                    )

            return results
        except Exception as e:
            logger.error(f"Error searching Chroma collection '{self.collection_name}': {e}")
            return []

    def get_stats(self) -> Dict[str, Any]:
        """Returns collection info including point count, backend, and mode."""
        try:
            if self.collection is None:
                return {
                    "backend": "chroma",
                    "mode": self.mode,
                    "collection_name": self.collection_name,
                    "exists": False,
                    "points_count": 0,
                    "status": "not_initialized",
                    "location": self.location,
                }
            count = self.collection.count()
            return {
                "backend": "chroma",
                "mode": self.mode,
                "collection_name": self.collection_name,
                "exists": True,
                "points_count": count,
                "status": "ok",
                "location": self.location,
            }
        except Exception as e:
            logger.error(f"Error getting stats for Chroma collection '{self.collection_name}': {e}")
            return {
                "backend": "chroma",
                "mode": self.mode,
                "collection_name": self.collection_name,
                "exists": False,
                "error": str(e),
                "location": self.location,
            }

    def health_check(self) -> Tuple[bool, str]:
        """Validates connection and readiness of the backend."""
        try:
            hb = self.client.heartbeat()
            count = self.collection.count() if self.collection is not None else 0
            return True, f"Chroma ({self.mode} @ {self.location}) is healthy; heartbeat: {hb}, collection '{self.collection_name}' count: {count}"
        except Exception as e:
            return False, f"Chroma ({self.mode}) health check failed: {e}"

    def close(self):
        """Cleanly close Chroma client handle if applicable."""
        pass

