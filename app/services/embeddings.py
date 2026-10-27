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

EMBEDDING_PROVIDER = _initial_cfg["provider"]
DENSE_MODEL_NAME = _initial_cfg["dense_model"]
SPARSE_MODEL_NAME = _initial_cfg["sparse_model"]
EMBEDDING_NUM_THREADS = _initial_cfg["threads"]
EMBEDDING_BATCH_SIZE = _initial_cfg["batch_size"]
LITELLM_URL = _initial_cfg["litellm_url"]
LITELLM_API_KEY = _initial_cfg.get("litellm_api_key", os.getenv("LITELLM_API_KEY", "dummy"))
VISION_OCR_MODEL = _initial_cfg.get("vision_ocr_model", os.getenv("VISION_OCR_MODEL", ""))
CHAT_MODEL = _initial_cfg.get("chat_model", os.getenv("CHAT_MODEL", ""))

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
):
    global _dense_model, _sparse_model, _openai_client
    global EMBEDDING_PROVIDER, DENSE_MODEL_NAME, SPARSE_MODEL_NAME
    global EMBEDDING_NUM_THREADS, EMBEDDING_BATCH_SIZE, LITELLM_URL, LITELLM_API_KEY
    global VISION_OCR_MODEL, CHAT_MODEL

    cfg = _get_db_emb_config()

    EMBEDDING_PROVIDER = (provider or cfg.get("provider") or "local").lower().strip()
    DENSE_MODEL_NAME = (dense_model or cfg.get("dense_model") or "BAAI/bge-small-en-v1.5").strip()
    SPARSE_MODEL_NAME = (sparse_model or cfg.get("sparse_model") or "Qdrant/bm25").strip()
    EMBEDDING_NUM_THREADS = int(threads if threads is not None else cfg.get("threads", 2))
    EMBEDDING_BATCH_SIZE = int(batch_size if batch_size is not None else cfg.get("batch_size", 32))
    LITELLM_URL = (litellm_url or cfg.get("litellm_url") or "http://litellm:4000/v1").strip()
    LITELLM_API_KEY = (litellm_api_key or cfg.get("litellm_api_key") or "dummy").strip()
    VISION_OCR_MODEL = (vision_ocr_model if vision_ocr_model is not None else (cfg.get("vision_ocr_model") or os.getenv("VISION_OCR_MODEL", ""))).strip()
    CHAT_MODEL = (chat_model if chat_model is not None else (cfg.get("chat_model") or os.getenv("CHAT_MODEL", ""))).strip()

    # Set underlying OpenMP / BLAS thread guard
    os.environ["OMP_NUM_THREADS"] = str(EMBEDDING_NUM_THREADS)

    if EMBEDDING_PROVIDER == "local":
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
            logger.error(f"Failed to initialize local FastEmbed models: {e}. Falling back to API.")
            EMBEDDING_PROVIDER = "api"
            
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

# Auto-initialize on import
init_embeddings()

def get_embedding_config() -> Dict[str, Any]:
    """Returns current active embedding configuration along with system hardware stats."""
    try:
        from app.services.database import detect_system_resources
        sys_res = detect_system_resources()
    except Exception:
        sys_res = {"cpus": os.cpu_count() or 2, "memory_gb": 4.0}

    return {
        "provider": EMBEDDING_PROVIDER,
        "dense_model": DENSE_MODEL_NAME,
        "sparse_model": SPARSE_MODEL_NAME,
        "threads": EMBEDDING_NUM_THREADS,
        "batch_size": EMBEDDING_BATCH_SIZE,
        "litellm_url": LITELLM_URL,
        "vision_ocr_model": VISION_OCR_MODEL,
        "chat_model": CHAT_MODEL,
        "system_cpus": sys_res["cpus"],
        "system_memory_gb": sys_res["memory_gb"],
    }

def get_dense_dim_for_config(
    provider: Optional[str] = None,
    dense_model: Optional[str] = None,
    litellm_url: Optional[str] = None,
    litellm_api_key: Optional[str] = None,
    threads: Optional[int] = None,
) -> int:
    """Probes dense embedding dimension for candidate configuration parameters without mutating global state."""
    target_provider = (provider or EMBEDDING_PROVIDER or "local").lower().strip()
    target_dense = (dense_model or DENSE_MODEL_NAME or "BAAI/bge-small-en-v1.5").strip()
    target_url = (litellm_url or LITELLM_URL or "http://litellm:4000/v1").strip()
    target_key = (litellm_api_key or LITELLM_API_KEY or "dummy").strip()
    target_threads = int(threads if threads is not None else EMBEDDING_NUM_THREADS)

    if target_provider == "local":
        try:
            from fastembed import TextEmbedding
            temp_model = TextEmbedding(model_name=target_dense, threads=target_threads)
            res = list(temp_model.embed(["dimension test"], batch_size=1))
            return len(res[0])
        except Exception as e:
            logger.warning(f"Failed to probe local FastEmbed model '{target_dense}': {e}. Falling back to API probe.")
            target_provider = "api"

    if target_provider == "api":
        from openai import OpenAI
        from app.services.llm_client import get_llm_extra_headers
        temp_client = OpenAI(
            base_url=target_url,
            api_key=target_key,
            default_headers=get_llm_extra_headers(),
        )
        response = temp_client.embeddings.create(
            input=["dimension test"],
            model=target_dense
        )
        return len(response.data[0].embedding)

    raise ValueError(f"Unsupported provider '{target_provider}' for dimension probe.")


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
    rebuild_index: bool = False,
) -> Dict[str, Any]:
    """Updates embedding configuration in SQLite and hot-reloads models in memory.

    If model or dimensions change and existing vector points/indexed files exist,
    requires rebuild_index=True to perform a coordinated reset and reindex.
    """
    from app.services.database import set_embedding_db_config, clear_indexing_metadata, get_db_connection
    from app.services.vector_store import get_vector_store

    target_provider = (provider or EMBEDDING_PROVIDER).lower().strip()
    target_dense = (dense_model or DENSE_MODEL_NAME).strip()

    # Check if active index contains indexed content
    has_indexed_content = False
    try:
        store = get_vector_store()
        stats = store.get_stats()
        points_cnt = stats.get("points_count", 0)
        with get_db_connection() as conn:
            files_cnt = conn.execute("SELECT count(*) FROM indexed_files").fetchone()[0]
        if points_cnt > 0 or files_cnt > 0:
            has_indexed_content = True
    except Exception as e:
        logger.debug(f"Error checking active index count: {e}")

    # Calculate candidate dimension and check for changes
    new_dim = None
    try:
        new_dim = get_dense_dim_for_config(
            provider=target_provider,
            dense_model=target_dense,
            litellm_url=litellm_url,
            litellm_api_key=litellm_api_key,
            threads=threads,
        )
    except Exception as probe_err:
        logger.warning(f"Failed to probe candidate embedding dimension: {probe_err}")

    current_dim = None
    try:
        current_dim = get_dense_dim()
    except Exception:
        pass

    dim_changed = (new_dim is not None and current_dim is not None and new_dim != current_dim)
    model_changed = (target_dense != DENSE_MODEL_NAME or target_provider != EMBEDDING_PROVIDER)

    if has_indexed_content and (dim_changed or model_changed) and not rebuild_index:
        msg = (
            f"Embedding configuration change detected (provider: '{EMBEDDING_PROVIDER}' -> '{target_provider}', "
            f"model: '{DENSE_MODEL_NAME}' -> '{target_dense}', dim: {current_dim}d -> {new_dim}d). "
            f"Active index contains existing vectors. Explicit rebuild confirmation is required (set 'rebuild_index': true)."
        )
        raise ValueError(msg)

    # Apply configuration update
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
    )

    if (dim_changed or model_changed or rebuild_index) and has_indexed_content:
        logger.info("Coordinating safe index rebuild for embedding model change...")
        clear_indexing_metadata()
        try:
            store = get_vector_store(force_reload=True)
            store.ensure_collection()
        except Exception as e:
            logger.error(f"Failed to recreate vector collection during model transition: {e}")

        try:
            from app.services.indexing import run_full_indexing
            threading.Thread(target=run_full_indexing, daemon=True).start()
        except Exception as re_err:
            logger.error(f"Failed to dispatch background reindexing pass: {re_err}")

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
    if EMBEDDING_PROVIDER == "local" and _dense_model is not None:
        with _dense_lock:
            embeddings = list(_dense_model.embed(texts, batch_size=bs))
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
