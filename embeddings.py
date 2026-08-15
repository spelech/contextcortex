import os
import logging
import threading
from typing import List, Dict, Any, Optional, Tuple
from qdrant_client.http import models as qmodels

logger = logging.getLogger("notes-rag-mcp.embeddings")

EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "local").lower()
DENSE_MODEL_NAME = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
SPARSE_MODEL_NAME = os.getenv("SPARSE_MODEL", "Qdrant/bm25")
LITELLM_URL = os.getenv("LITELLM_URL", "http://litellm:4000/v1")
LITELLM_API_KEY = os.getenv("LITELLM_API_KEY", "dummy")

_dense_model = None
_sparse_model = None
_dense_lock = threading.Lock()
_sparse_lock = threading.Lock()
_openai_client = None

def init_embeddings():
    global _dense_model, _sparse_model, _openai_client, EMBEDDING_PROVIDER
    if EMBEDDING_PROVIDER == "local":
        try:
            from fastembed import TextEmbedding, SparseTextEmbedding
            logger.info(f"Initializing FastEmbed dense model: {DENSE_MODEL_NAME}")
            _dense_model = TextEmbedding(model_name=DENSE_MODEL_NAME)
            logger.info(f"Initializing FastEmbed sparse model: {SPARSE_MODEL_NAME}")
            _sparse_model = SparseTextEmbedding(model_name=SPARSE_MODEL_NAME)
            logger.info("FastEmbed dense & sparse models initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize local FastEmbed models: {e}. Falling back to API.")
            EMBEDDING_PROVIDER = "api"
            
    if EMBEDDING_PROVIDER == "api":
        try:
            from openai import OpenAI
            logger.info(f"Using OpenAI/LiteLLM API embeddings at {LITELLM_URL} model {DENSE_MODEL_NAME}")
            _openai_client = OpenAI(base_url=LITELLM_URL, api_key=LITELLM_API_KEY)
            # Try initializing sparse model locally even if dense uses API
            try:
                from fastembed import SparseTextEmbedding
                _sparse_model = SparseTextEmbedding(model_name=SPARSE_MODEL_NAME)
            except Exception:
                _sparse_model = None
        except Exception as oe:
            logger.error(f"Failed to initialize API client: {oe}")

# Auto-initialize on import
init_embeddings()

def get_dense_embedding(text: str) -> List[float]:
    """Generates dense vector embedding (e.g. 384 dimensions)."""
    return get_dense_embeddings_batch([text])[0]

def get_dense_embeddings_batch(texts: List[str]) -> List[List[float]]:
    """Generates a batch of dense vector embeddings efficiently in ONNX."""
    if not texts:
        return []
    if EMBEDDING_PROVIDER == "local" and _dense_model is not None:
        with _dense_lock:
            embeddings = list(_dense_model.embed(texts))
            return [e.tolist() for e in embeddings]
    else:
        if _openai_client is None:
            raise RuntimeError("API Embedding client not initialized.")
        response = _openai_client.embeddings.create(
            input=texts,
            model=DENSE_MODEL_NAME
        )
        return [d.embedding for d in response.data]

def get_sparse_embedding(text: str) -> Optional[qmodels.SparseVector]:
    """Generates BM25 sparse vector embedding for a single text."""
    res = get_sparse_embeddings_batch([text])
    return res[0] if res else None

def get_sparse_embeddings_batch(texts: List[str]) -> List[Optional[qmodels.SparseVector]]:
    """Generates a batch of BM25 sparse vector embeddings."""
    if not texts:
        return []
    if _sparse_model is not None:
        try:
            with _sparse_lock:
                sparse_res = list(_sparse_model.embed(texts))
                return [
                    qmodels.SparseVector(
                        indices=s.indices.tolist(),
                        values=s.values.tolist()
                    ) for s in sparse_res
                ]
        except Exception as e:
            logger.warning(f"Failed to generate sparse embeddings batch: {e}")
            return [None] * len(texts)
    return [None] * len(texts)

def get_hybrid_embeddings(text: str) -> Dict[str, Any]:
    """Returns a dict with dense vector and optional sparse vector for Qdrant named vectors."""
    res = get_hybrid_embeddings_batch([text])
    return res[0] if res else {}

def get_hybrid_embeddings_batch(texts: List[str]) -> List[Dict[str, Any]]:
    """Returns a list of dicts with dense vector and optional sparse vector for batch upserts."""
    if not texts:
        return []
    dense_vecs = get_dense_embeddings_batch(texts)
    sparse_vecs = get_sparse_embeddings_batch(texts)
    
    results = []
    for i, dense in enumerate(dense_vecs):
        vec_dict = {"dense": dense}
        if i < len(sparse_vecs) and sparse_vecs[i] is not None:
            vec_dict["sparse"] = sparse_vecs[i]
        results.append(vec_dict)
    return results

def get_dense_dim() -> int:
    """Calculates embedding dimension from a sample text."""
    sample = get_dense_embedding("dimension test")
    return len(sample)
