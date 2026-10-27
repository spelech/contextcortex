import os
import logging
import threading
from typing import List, Dict, Any, Optional, Tuple
from qdrant_client.http import models as qmodels

logger = logging.getLogger("contextcortex.embeddings")

def _get_db_emb_config() -> Dict[str, Any]:
    try:
        from app.services.database import get_embedding_db_config
        return get_embedding_db_config()
    except Exception:
        from app.services.database.connection import _resolve_default_embedding_config
        return _resolve_default_embedding_config()

_initial_cfg = _get_db_emb_config()

REQUESTED_PROVIDER = _initial_cfg["provider"]
EMBEDDING_PROVIDER = _initial_cfg["provider"]
REQUESTED_DENSE_MODEL = _initial_cfg["dense_model"]
DENSE_MODEL_NAME = _initial_cfg["dense_model"]
SPARSE_MODEL_NAME = _initial_cfg["sparse_model"]
EMBEDDING_NUM_THREADS = _initial_cfg["threads"]
EMBEDDING_BATCH_SIZE = _initial_cfg["batch_size"]
LITELLM_URL = _initial_cfg["litellm_url"]
LITELLM_API_KEY = _initial_cfg.get("litellm_api_key", os.getenv("LITELLM_API_KEY", "dummy"))
VISION_OCR_MODEL = _initial_cfg.get("vision_ocr_model", os.getenv("VISION_OCR_MODEL", ""))
CHAT_MODEL = _initial_cfg.get("chat_model", os.getenv("CHAT_MODEL", ""))
ALLOW_FALLBACK = _initial_cfg.get("allow_fallback", False)
FALLBACK_DENSE_MODEL = _initial_cfg.get("fallback_dense_model", "")

_dense_model = None
_sparse_model = None
_dense_lock = threading.Lock()
_sparse_lock = threading.Lock()
_openai_client = None

def init_embeddings(
    provider: Optional[str] = None,
    dense_model: Optional[str] = None,
    sparse_model: Optional[str] = None,
    threads: Optional[int] = None,
    batch_size: Optional[int] = None,
    litellm_url: Optional[str] = None,
    litellm_api_key: Optional[str] = None,
    vision_ocr_model: Optional[str] = None,
    chat_model: Optional[str] = None,
    allow_fallback: Optional[bool] = None,
    fallback_dense_model: Optional[str] = None,
):
    global _dense_model, _sparse_model, _openai_client
    global REQUESTED_PROVIDER, EMBEDDING_PROVIDER
    global REQUESTED_DENSE_MODEL, DENSE_MODEL_NAME, SPARSE_MODEL_NAME
    global EMBEDDING_NUM_THREADS, EMBEDDING_BATCH_SIZE, LITELLM_URL, LITELLM_API_KEY
    global VISION_OCR_MODEL, CHAT_MODEL, ALLOW_FALLBACK, FALLBACK_DENSE_MODEL

    cfg = _get_db_emb_config()

    REQUESTED_PROVIDER = (provider or cfg.get("provider") or "local").lower().strip()
    EMBEDDING_PROVIDER = REQUESTED_PROVIDER
    REQUESTED_DENSE_MODEL = (dense_model or cfg.get("dense_model") or "BAAI/bge-small-en-v1.5").strip()
    DENSE_MODEL_NAME = REQUESTED_DENSE_MODEL
    SPARSE_MODEL_NAME = (sparse_model or cfg.get("sparse_model") or "Qdrant/bm25").strip()
    EMBEDDING_NUM_THREADS = int(threads if threads is not None else cfg.get("threads", 2))
    EMBEDDING_BATCH_SIZE = int(batch_size if batch_size is not None else cfg.get("batch_size", 32))
    LITELLM_URL = (litellm_url or cfg.get("litellm_url") or "http://litellm:4000/v1").strip()
    LITELLM_API_KEY = (litellm_api_key or cfg.get("litellm_api_key") or "dummy").strip()
    VISION_OCR_MODEL = (vision_ocr_model if vision_ocr_model is not None else (cfg.get("vision_ocr_model") or os.getenv("VISION_OCR_MODEL", ""))).strip()
    CHAT_MODEL = (chat_model if chat_model is not None else (cfg.get("chat_model") or os.getenv("CHAT_MODEL", ""))).strip()
    ALLOW_FALLBACK = allow_fallback if allow_fallback is not None else cfg.get("allow_fallback", False)
    FALLBACK_DENSE_MODEL = (fallback_dense_model if fallback_dense_model is not None else cfg.get("fallback_dense_model", "")).strip()

    # Set underlying OpenMP / BLAS thread guard
    os.environ["OMP_NUM_THREADS"] = str(EMBEDDING_NUM_THREADS)

    with _dense_lock:
        _dense_model = None
    with _sparse_lock:
        _sparse_model = None
    _openai_client = None

    if REQUESTED_PROVIDER == "local":
        try:
            from fastembed import TextEmbedding, SparseTextEmbedding
            logger.info(f"Initializing FastEmbed dense model: {DENSE_MODEL_NAME} with threads={EMBEDDING_NUM_THREADS}")
            with _dense_lock:
                _dense_model = TextEmbedding(model_name=DENSE_MODEL_NAME, threads=EMBEDDING_NUM_THREADS)
            logger.info(f"Initializing FastEmbed sparse model: {SPARSE_MODEL_NAME} with threads={EMBEDDING_NUM_THREADS}")
            with _sparse_lock:
                _sparse_model = SparseTextEmbedding(model_name=SPARSE_MODEL_NAME, threads=EMBEDDING_NUM_THREADS)
            logger.info("FastEmbed dense & sparse models initialized successfully with resource limits.")
        except Exception as e:
            logger.error(f"Failed to initialize local FastEmbed models: {e}")
            with _dense_lock:
                _dense_model = None
            with _sparse_lock:
                _sparse_model = None

            if not ALLOW_FALLBACK:
                EMBEDDING_PROVIDER = "local"
                raise RuntimeError(
                    f"Local FastEmbed initialization failed for dense model '{DENSE_MODEL_NAME}': {e}. "
                    "Fallback to API is disabled (allow_fallback=False)."
                ) from e
            else:
                if not FALLBACK_DENSE_MODEL:
                    EMBEDDING_PROVIDER = "local"
                    raise ValueError(
                        f"Local FastEmbed initialization failed for '{DENSE_MODEL_NAME}': {e}, "
                        "and allow_fallback=True but no valid fallback_dense_model was configured."
                    ) from e
                logger.warning(f"Local FastEmbed initialization failed: {e}. Falling back to API with model '{FALLBACK_DENSE_MODEL}'.")
                EMBEDDING_PROVIDER = "api"
                DENSE_MODEL_NAME = FALLBACK_DENSE_MODEL

    if EMBEDDING_PROVIDER == "api":
        try:
            from openai import OpenAI
            from app.services.llm_client import get_llm_extra_headers
            logger.info(f"Using OpenAI/LiteLLM API embeddings at {LITELLM_URL} model {DENSE_MODEL_NAME}")
            _openai_client = OpenAI(
                base_url=LITELLM_URL,
                api_key=LITELLM_API_KEY,
                default_headers=get_llm_extra_headers(),
            )
            # Try initializing sparse model locally even if dense uses API
            try:
                from fastembed import SparseTextEmbedding
                with _sparse_lock:
                    _sparse_model = SparseTextEmbedding(model_name=SPARSE_MODEL_NAME, threads=EMBEDDING_NUM_THREADS)
            except Exception:
                _sparse_model = None
        except Exception as oe:
            logger.error(f"Failed to initialize API client: {oe}")
            if REQUESTED_PROVIDER == "local" and ALLOW_FALLBACK:
                raise RuntimeError(f"Fallback to API failed: {oe}") from oe

# Auto-initialize on import safely
try:
    init_embeddings()
except Exception as _e:
    logger.warning(f"Initial embedding auto-init failed: {_e}")

def get_embedding_config() -> Dict[str, Any]:
    """Returns current active embedding configuration along with system hardware stats."""
    try:
        from app.services.database import detect_system_resources
        sys_res = detect_system_resources()
    except Exception:
        sys_res = {"cpus": os.cpu_count() or 2, "memory_gb": 4.0}

    return {
        "provider": EMBEDDING_PROVIDER,
        "requested_provider": REQUESTED_PROVIDER,
        "effective_provider": EMBEDDING_PROVIDER,
        "dense_model": DENSE_MODEL_NAME,
        "requested_dense_model": REQUESTED_DENSE_MODEL,
        "effective_dense_model": DENSE_MODEL_NAME,
        "sparse_model": SPARSE_MODEL_NAME,
        "threads": EMBEDDING_NUM_THREADS,
        "batch_size": EMBEDDING_BATCH_SIZE,
        "litellm_url": LITELLM_URL,
        "vision_ocr_model": VISION_OCR_MODEL,
        "chat_model": CHAT_MODEL,
        "allow_fallback": ALLOW_FALLBACK,
        "fallback_dense_model": FALLBACK_DENSE_MODEL,
        "system_cpus": sys_res["cpus"],
        "system_memory_gb": sys_res["memory_gb"],
    }

def update_embedding_config(
    provider: Optional[str] = None,
    dense_model: Optional[str] = None,
    sparse_model: Optional[str] = None,
    threads: Optional[int] = None,
    batch_size: Optional[int] = None,
    litellm_url: Optional[str] = None,
    litellm_api_key: Optional[str] = None,
    vision_ocr_model: Optional[str] = None,
    chat_model: Optional[str] = None,
    allow_fallback: Optional[bool] = None,
    fallback_dense_model: Optional[str] = None,
) -> Dict[str, Any]:
    """Updates embedding configuration in SQLite and hot-reloads models in memory."""
    from app.services.database import set_embedding_db_config
    set_embedding_db_config(
        provider=provider,
        dense_model=dense_model,
        sparse_model=sparse_model,
        threads=threads,
        batch_size=batch_size,
        litellm_url=litellm_url,
        litellm_api_key=litellm_api_key,
        vision_ocr_model=vision_ocr_model,
        chat_model=chat_model,
        allow_fallback=allow_fallback,
        fallback_dense_model=fallback_dense_model,
    )
    init_embeddings(
        provider=provider,
        dense_model=dense_model,
        sparse_model=sparse_model,
        threads=threads,
        batch_size=batch_size,
        litellm_url=litellm_url,
        litellm_api_key=litellm_api_key,
        vision_ocr_model=vision_ocr_model,
        chat_model=chat_model,
        allow_fallback=allow_fallback,
        fallback_dense_model=fallback_dense_model,
    )
    return get_embedding_config()

def get_dense_embedding(text: str) -> List[float]:
    """Generates dense vector embedding (e.g. 384 dimensions)."""
    res = get_dense_embeddings_batch([text])
    return res[0] if res else [0.0] * 384

def get_dense_embeddings_batch(texts: List[str], batch_size: Optional[int] = None) -> List[List[float]]:
    """Generates a batch of dense vector embeddings efficiently in ONNX."""
    if not texts:
        return []
    bs = batch_size or EMBEDDING_BATCH_SIZE
    if EMBEDDING_PROVIDER == "local":
        if _dense_model is None:
            raise RuntimeError("Local dense embedding model is not initialized.")
        with _dense_lock:
            embeddings = list(_dense_model.embed(texts, batch_size=bs))
            return [e.tolist() for e in embeddings]
    elif EMBEDDING_PROVIDER == "api":
        if _openai_client is None:
            raise RuntimeError("API Embedding client not initialized.")
        response = _openai_client.embeddings.create(
            input=texts,
            model=DENSE_MODEL_NAME
        )
        return [d.embedding for d in response.data]
    else:
        raise RuntimeError(f"Unknown embedding provider: {EMBEDDING_PROVIDER}")

def get_sparse_embedding(text: str) -> Optional[qmodels.SparseVector]:
    """Generates BM25 sparse vector embedding for a single text."""
    res = get_sparse_embeddings_batch([text])
    return res[0] if res else None

def get_sparse_embeddings_batch(texts: List[str], batch_size: Optional[int] = None) -> List[Optional[qmodels.SparseVector]]:
    """Generates a batch of BM25 sparse vector embeddings."""
    if not texts:
        return []
    bs = batch_size or EMBEDDING_BATCH_SIZE
    if _sparse_model is not None:
        try:
            with _sparse_lock:
                sparse_res = list(_sparse_model.embed(texts, batch_size=bs))
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
