import os
import sys
import sqlite3
import logging
from typing import Optional, Dict, Any

from sqlalchemy import select

from app.services.database.schema import TABLES
from app.services.database.engine import (
    get_default_db_path,
    get_db_engine,
    get_connection,
    init_db as engine_init_db,
    is_postgres,
)

logger = logging.getLogger("contextcortex.db")

CACHE_DB_PATH = get_default_db_path()
try:
    os.makedirs(os.path.dirname(CACHE_DB_PATH), exist_ok=True)
except Exception:
    pass


def get_db_connection() -> sqlite3.Connection:
    """
    Returns a SQLite database connection for backward compatibility with legacy modules.
    """
    db_mod = sys.modules.get("app.services.database")
    if db_mod and hasattr(db_mod, "CACHE_DB_PATH") and db_mod.CACHE_DB_PATH:
        db_path = db_mod.CACHE_DB_PATH
    else:
        conn_mod = sys.modules.get("app.services.database.connection")
        if conn_mod and hasattr(conn_mod, "CACHE_DB_PATH") and conn_mod.CACHE_DB_PATH:
            db_path = conn_mod.CACHE_DB_PATH
        else:
            db_path = CACHE_DB_PATH

    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db(vault_path: str = "/docs", engine=None):
    """
    Initializes database schema and seed data via SQLAlchemy Core engine.
    """
    return engine_init_db(vault_path=vault_path, engine=engine)


def get_metadata(key: str, default: Optional[str] = None) -> Optional[str]:
    try:
        with get_connection() as conn:
            val = conn.execute(
                select(TABLES["system_metadata"].c.value).where(TABLES["system_metadata"].c.key == key)
            ).scalar()
            return str(val) if val is not None else default
    except Exception:
        return default


def set_metadata(key: str, value: str):
    try:
        with get_connection() as conn:
            conn.execute(
                TABLES["system_metadata"].delete().where(TABLES["system_metadata"].c.key == key)
            )
            conn.execute(
                TABLES["system_metadata"].insert().values(key=key, value=str(value))
            )
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to set metadata key {key}: {e}")


def get_default_vector_storage_path() -> str:
    env_path = os.getenv("VECTOR_STORE_STORAGE_PATH")
    if env_path:
        return env_path
    if os.path.exists("/app") and os.access("/app", os.W_OK):
        return "/app/data/vector_storage"
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "vector_storage")


def _resolve_default_vector_store_config(conn: Optional[Any] = None) -> Dict[str, str]:
    provider = os.getenv("VECTOR_STORE") or os.getenv("VECTOR_STORE_PROVIDER") or (
        "pgvector" if is_postgres() else "qdrant"
    )
    provider = provider.lower().strip()

    mode = os.getenv("VECTOR_STORE_MODE")
    if not mode:
        if provider == "qdrant":
            q_url = os.getenv("QDRANT_URL")
            if q_url and q_url.strip() and not q_url.strip().startswith(":memory:"):
                mode = "remote"
            else:
                mode = "embedded"
        elif provider in ("chroma", "chromadb"):
            c_url = os.getenv("CHROMA_URL")
            if c_url and c_url.strip():
                mode = "remote"
            else:
                mode = "embedded"
        elif provider in ("pgvector", "postgres", "postgresql"):
            mode = "remote"
        else:
            mode = "embedded"
    mode = mode.lower().strip()

    storage_path = os.getenv("VECTOR_STORE_STORAGE_PATH") or get_default_vector_storage_path()

    if provider == "qdrant":
        url = os.getenv("VECTOR_STORE_URL") or os.getenv("QDRANT_URL") or ""
    elif provider in ("chroma", "chromadb"):
        url = os.getenv("VECTOR_STORE_URL") or os.getenv("CHROMA_URL") or ""
    elif provider in ("pgvector", "postgres", "postgresql"):
        url = os.getenv("DATABASE_URL") or ""
    else:
        url = os.getenv("VECTOR_STORE_URL") or ""

    collection = os.getenv("VECTOR_STORE_COLLECTION") or os.getenv("COLLECTION_NAME") or "knowledge_rag_v1"

    return {
        "provider": provider,
        "mode": mode,
        "storage_path": storage_path,
        "url": url.strip(),
        "collection": collection.strip(),
    }


def get_vector_store_db_config() -> Dict[str, str]:
    provider = get_metadata("vector_store_provider")
    mode = get_metadata("vector_store_mode")
    storage_path = get_metadata("vector_store_storage_path")
    url = get_metadata("vector_store_url")
    collection = get_metadata("vector_store_collection")

    default_cfg = _resolve_default_vector_store_config()

    return {
        "provider": (provider or default_cfg["provider"]).lower().strip(),
        "mode": (mode or default_cfg["mode"]).lower().strip(),
        "storage_path": storage_path or default_cfg["storage_path"],
        "url": (url if url is not None else default_cfg["url"]).strip(),
        "collection": (collection or default_cfg["collection"]).strip(),
    }


def set_vector_store_db_config(
    provider: Optional[str] = None,
    mode: Optional[str] = None,
    storage_path: Optional[str] = None,
    url: Optional[str] = None,
    collection: Optional[str] = None,
):
    if provider is not None:
        set_metadata("vector_store_provider", provider.lower().strip())
    if mode is not None:
        set_metadata("vector_store_mode", mode.lower().strip())
    if storage_path is not None:
        set_metadata("vector_store_storage_path", storage_path.strip())
    if url is not None:
        set_metadata("vector_store_url", url.strip())
    if collection is not None:
        set_metadata("vector_store_collection", collection.strip())


def detect_system_resources() -> Dict[str, Any]:
    """Detects available CPU cores and RAM in the execution environment, respecting container quotas."""
    import math
    cpus = os.cpu_count() or 2
    # Check cgroup v2
    if os.path.exists("/sys/fs/cgroup/cpu.max"):
        try:
            with open("/sys/fs/cgroup/cpu.max", "r") as f:
                parts = f.read().strip().split()
                if len(parts) == 2 and parts[0] != "max":
                    quota, period = float(parts[0]), float(parts[1])
                    if period > 0:
                        cpus = max(1, math.ceil(quota / period))
        except Exception:
            pass
    # Check cgroup v1
    elif os.path.exists("/sys/fs/cgroup/cpu/cpu.cfs_quota_us") and os.path.exists("/sys/fs/cgroup/cpu/cpu.cfs_period_us"):
        try:
            with open("/sys/fs/cgroup/cpu/cpu.cfs_quota_us", "r") as f_q, open("/sys/fs/cgroup/cpu/cpu.cfs_period_us", "r") as f_p:
                quota = float(f_q.read().strip())
                period = float(f_p.read().strip())
                if quota > 0 and period > 0:
                    cpus = max(1, math.ceil(quota / period))
        except Exception:
            pass

    mem_gb = 4.0
    try:
        if hasattr(os, "sysconf") and "SC_PAGE_SIZE" in os.sysconf_names and "SC_PHYS_PAGES" in os.sysconf_names:
            mem_bytes = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
            mem_gb = round(mem_bytes / (1024 ** 3), 1)
    except Exception:
        pass
    return {"cpus": cpus, "memory_gb": mem_gb}


def _resolve_default_embedding_config(conn: Optional[Any] = None) -> Dict[str, Any]:
    sys_res = detect_system_resources()
    default_threads = min(2, max(1, sys_res["cpus"]))

    env_threads = os.getenv("EMBEDDING_NUM_THREADS") or os.getenv("EMBEDDING_THREADS")
    threads = int(env_threads) if env_threads and env_threads.isdigit() else default_threads

    env_batch = os.getenv("EMBEDDING_BATCH_SIZE")
    batch_size = int(env_batch) if env_batch and env_batch.isdigit() else 32

    provider = os.getenv("EMBEDDING_PROVIDER", "local").lower().strip()
    dense_model = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5").strip()
    sparse_model = os.getenv("SPARSE_MODEL", "Qdrant/bm25").strip()
    litellm_url = os.getenv("LITELLM_URL", "http://litellm:4000/v1").strip()
    litellm_api_key = os.getenv("LITELLM_API_KEY", "dummy").strip()

    return {
        "provider": provider,
        "dense_model": dense_model,
        "sparse_model": sparse_model,
        "threads": max(1, threads),
        "batch_size": max(1, batch_size),
        "litellm_url": litellm_url,
        "litellm_api_key": litellm_api_key,
        "system_cpus": sys_res["cpus"],
        "system_memory_gb": sys_res["memory_gb"],
    }


def get_embedding_db_config() -> Dict[str, Any]:
    provider = get_metadata("embedding_provider")
    dense_model = get_metadata("embedding_dense_model")
    sparse_model = get_metadata("embedding_sparse_model")
    threads_str = get_metadata("embedding_num_threads")
    batch_size_str = get_metadata("embedding_batch_size")
    litellm_url = get_metadata("embedding_litellm_url")
    litellm_api_key = get_metadata("embedding_litellm_api_key")

    default_cfg = _resolve_default_embedding_config()

    threads = int(threads_str) if threads_str and threads_str.isdigit() else default_cfg["threads"]
    batch_size = int(batch_size_str) if batch_size_str and batch_size_str.isdigit() else default_cfg["batch_size"]

    return {
        "provider": (provider or default_cfg["provider"]).lower().strip(),
        "dense_model": (dense_model or default_cfg["dense_model"]).strip(),
        "sparse_model": (sparse_model or default_cfg["sparse_model"]).strip(),
        "threads": max(1, threads),
        "batch_size": max(1, batch_size),
        "litellm_url": (litellm_url or default_cfg["litellm_url"]).strip(),
        "litellm_api_key": litellm_api_key or default_cfg["litellm_api_key"],
        "system_cpus": default_cfg["system_cpus"],
        "system_memory_gb": default_cfg["system_memory_gb"],
    }


def set_embedding_db_config(
    provider: Optional[str] = None,
    dense_model: Optional[str] = None,
    sparse_model: Optional[str] = None,
    threads: Optional[int] = None,
    batch_size: Optional[int] = None,
    litellm_url: Optional[str] = None,
    litellm_api_key: Optional[str] = None,
):
    if provider is not None:
        set_metadata("embedding_provider", provider.lower().strip())
    if dense_model is not None:
        set_metadata("embedding_dense_model", dense_model.strip())
    if sparse_model is not None:
        set_metadata("embedding_sparse_model", sparse_model.strip())
    if threads is not None:
        set_metadata("embedding_num_threads", str(max(1, threads)))
    if batch_size is not None:
        set_metadata("embedding_batch_size", str(max(1, batch_size)))
    if litellm_url is not None:
        set_metadata("embedding_litellm_url", litellm_url.strip())
    if litellm_api_key is not None:
        set_metadata("embedding_litellm_api_key", litellm_api_key.strip())
