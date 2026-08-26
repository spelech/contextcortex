import os
import json
import sqlite3
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger("contextcortex.db")

def get_default_db_path() -> str:
    env_path = os.getenv("CACHE_DB_PATH")
    if env_path:
        return env_path
    if os.path.exists("/app") and os.access("/app", os.W_OK):
        return "/app/data/index_cache.db"
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "index_cache.db")

CACHE_DB_PATH = get_default_db_path()
try:
    os.makedirs(os.path.dirname(CACHE_DB_PATH), exist_ok=True)
except Exception:
    pass

def get_db_connection() -> sqlite3.Connection:
    import sys
    db_mod = sys.modules.get("app.services.database")
    if db_mod and hasattr(db_mod, "CACHE_DB_PATH"):
        db_path = db_mod.CACHE_DB_PATH
    else:
        db_path = CACHE_DB_PATH
    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn

def init_db(vault_path: str = "/docs"):
    with get_db_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS indexed_paths (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT UNIQUE,
                type TEXT,
                recursive INTEGER,
                enabled INTEGER DEFAULT 1,
                category TEXT,
                repo TEXT DEFAULT 'local',
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS git_repositories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                url TEXT NOT NULL,
                branch TEXT DEFAULT 'main',
                commit_sha TEXT,
                auth_token TEXT,
                provider TEXT DEFAULT 'github',
                auth_user TEXT,
                enabled INTEGER DEFAULT 1,
                auto_sync INTEGER DEFAULT 1,
                webhook_secret TEXT,
                status TEXT DEFAULT 'pending',
                last_error TEXT,
                last_synced TIMESTAMP,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        try:
            conn.execute("ALTER TABLE git_repositories ADD COLUMN last_error TEXT")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE git_repositories ADD COLUMN provider TEXT DEFAULT 'github'")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE git_repositories ADD COLUMN auth_user TEXT")
        except Exception:
            pass
        try:
            repo_cols = [r[1] for r in conn.execute("PRAGMA table_info(git_repositories)").fetchall()]
            if "auto_sync" not in repo_cols:
                conn.execute("ALTER TABLE git_repositories ADD COLUMN auto_sync INTEGER DEFAULT 1")
            if "webhook_secret" not in repo_cols:
                conn.execute("ALTER TABLE git_repositories ADD COLUMN webhook_secret TEXT")
        except Exception:
            pass

        conn.execute("""
            CREATE TABLE IF NOT EXISTS git_host_credentials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                host TEXT UNIQUE NOT NULL,
                provider TEXT NOT NULL,
                auth_user TEXT,
                auth_token TEXT NOT NULL,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_git_host_credentials_host ON git_host_credentials(host)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS indexed_files (
                filepath TEXT PRIMARY KEY,
                repo TEXT DEFAULT 'local',
                doc_type TEXT DEFAULT 'doc',
                language TEXT DEFAULT 'text',
                commit_sha TEXT,
                mtime REAL,
                hash TEXT
            )
        """)
        for col, default in [("doc_type", "'doc'"), ("language", "'text'"), ("commit_sha", "NULL"), ("mtime", "NULL"), ("hash", "NULL")]:
            try:
                conn.execute(f"ALTER TABLE indexed_files ADD COLUMN {col} TEXT DEFAULT {default}")
            except Exception:
                pass
        conn.execute("CREATE INDEX IF NOT EXISTS idx_indexed_files_repo_hash ON indexed_files(repo, hash)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_indexed_files_repo ON indexed_files(repo)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS file_summaries (
                filepath TEXT PRIMARY KEY,
                repo TEXT DEFAULT 'local',
                title TEXT,
                folder TEXT,
                category TEXT,
                tags TEXT,
                headings TEXT,
                keywords TEXT,
                mtime REAL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS embedding_cache (
                chunk_hash TEXT NOT NULL,
                dense_vector TEXT,
                sparse_indices TEXT,
                sparse_values TEXT,
                model_name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (chunk_hash, model_name)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_embedding_cache_model ON embedding_cache(model_name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_embedding_cache_model_hash ON embedding_cache(model_name, chunk_hash)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS ast_symbols (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                repo TEXT NOT NULL,
                filepath TEXT NOT NULL,
                name TEXT NOT NULL,
                full_symbol TEXT,
                kind TEXT NOT NULL,
                start_line INTEGER NOT NULL,
                end_line INTEGER NOT NULL,
                signature TEXT,
                language TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ast_symbols_name ON ast_symbols(name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ast_symbols_repo ON ast_symbols(repo)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS ast_relationships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                repo TEXT NOT NULL,
                source_symbol_id INTEGER,
                source_filepath TEXT NOT NULL,
                source_symbol TEXT NOT NULL,
                target_symbol TEXT NOT NULL,
                relationship_type TEXT NOT NULL,
                line_number INTEGER NOT NULL,
                FOREIGN KEY(source_symbol_id) REFERENCES ast_symbols(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ast_rel_repo_source ON ast_relationships(repo, source_symbol)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ast_rel_repo_target ON ast_relationships(repo, target_symbol)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ast_rel_type ON ast_relationships(relationship_type)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS api_routes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                repo TEXT NOT NULL,
                filepath TEXT NOT NULL,
                framework TEXT NOT NULL,
                http_method TEXT NOT NULL,
                path_pattern TEXT NOT NULL,
                handler_symbol TEXT,
                start_line INTEGER NOT NULL,
                end_line INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_api_routes_repo_path ON api_routes(repo, path_pattern)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_api_routes_method ON api_routes(http_method)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS api_client_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                repo TEXT NOT NULL,
                filepath TEXT NOT NULL,
                http_method TEXT,
                url_pattern TEXT NOT NULL,
                caller_symbol TEXT,
                line_number INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_api_calls_url ON api_client_calls(url_pattern)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS system_metadata (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS architecture_decision_records (
                id TEXT PRIMARY KEY,
                repo TEXT NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                context TEXT NOT NULL,
                decision TEXT NOT NULL,
                consequences TEXT,
                superseded_by TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_adr_repo_status ON architecture_decision_records(repo, status)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS custom_prompts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                description TEXT NOT NULL,
                arguments_json TEXT,
                template TEXT NOT NULL,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        try:
            prompt_count = conn.execute("SELECT count(*) FROM custom_prompts").fetchone()[0]
            if prompt_count == 0:
                default_prompts = [
                    (
                        "search_infrastructure_docs",
                        "Workflow to search system infrastructure documentation, container mappings, or network routes.",
                        json.dumps([{"name": "topic", "description": "The specific infrastructure topic to search for", "required": True}]),
                        "Please perform a search using the search_docs tool for topic '{topic}' and summarize the matching container mappings, port numbers, reverse proxy routes, or setup instructions."
                    ),
                    (
                        "find_implementation_symbol",
                        "Workflow to locate functions, classes, and logic across registered codebases.",
                        json.dumps([{"name": "symbol", "description": "Function or class name to find", "required": True}, {"name": "repo", "description": "Target repository (optional)", "required": False}]),
                        "Please use find_symbol for '{symbol}' in repo '{repo}' and inspect its declaration, line numbers, and implementation details."
                    )
                ]
                conn.executemany(
                    "INSERT OR IGNORE INTO custom_prompts (name, description, arguments_json, template) VALUES (?, ?, ?, ?)",
                    default_prompts
                )
        except Exception as pe:
            logger.error(f"Failed to seed default prompts: {pe}")

        try:
            conn.execute("DELETE FROM indexed_paths WHERE path = '/notes'")
            count = conn.execute("SELECT count(*) FROM indexed_paths").fetchone()[0]
            if count == 0 and os.path.exists(vault_path):
                conn.execute(
                    "INSERT OR IGNORE INTO indexed_paths (path, type, recursive, enabled, category, repo) VALUES (?, ?, ?, ?, ?, ?)",
                    (os.path.abspath(vault_path), "directory", 1, 1, "default", "vault")
                )
        except Exception as se:
            logger.error(f"Failed to seed default vault path: {se}")

        try:
            default_cfg = _resolve_default_vector_store_config(conn)
            for key, val in [
                ("vector_store_provider", default_cfg["provider"]),
                ("vector_store_mode", default_cfg["mode"]),
                ("vector_store_storage_path", default_cfg["storage_path"]),
                ("vector_store_url", default_cfg["url"]),
                ("vector_store_collection", default_cfg["collection"]),
            ]:
                row = conn.execute("SELECT value FROM system_metadata WHERE key = ?", (key,)).fetchone()
                if row is None:
                    conn.execute("INSERT INTO system_metadata (key, value) VALUES (?, ?)", (key, str(val)))
        except Exception as ve:
            logger.error(f"Failed to seed vector store configuration: {ve}")

        try:
            emb_cfg = _resolve_default_embedding_config(conn)
            for key, val in [
                ("embedding_provider", emb_cfg["provider"]),
                ("embedding_dense_model", emb_cfg["dense_model"]),
                ("embedding_sparse_model", emb_cfg["sparse_model"]),
                ("embedding_num_threads", str(emb_cfg["threads"])),
                ("embedding_batch_size", str(emb_cfg["batch_size"])),
                ("embedding_litellm_url", emb_cfg["litellm_url"]),
            ]:
                row = conn.execute("SELECT value FROM system_metadata WHERE key = ?", (key,)).fetchone()
                if row is None:
                    conn.execute("INSERT INTO system_metadata (key, value) VALUES (?, ?)", (key, str(val)))
        except Exception as ee:
            logger.error(f"Failed to seed embedding configuration: {ee}")

        conn.commit()

def get_metadata(key: str, default: Optional[str] = None) -> Optional[str]:
    try:
        with get_db_connection() as conn:
            row = conn.execute("SELECT value FROM system_metadata WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else default
    except Exception:
        return default

def set_metadata(key: str, value: str):
    try:
        with get_db_connection() as conn:
            conn.execute("INSERT OR REPLACE INTO system_metadata (key, value) VALUES (?, ?)", (key, value))
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

def _resolve_default_vector_store_config(conn: Optional[sqlite3.Connection] = None) -> Dict[str, str]:
    provider = os.getenv("VECTOR_STORE") or os.getenv("VECTOR_STORE_PROVIDER") or "qdrant"
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
        else:
            mode = "embedded"
    mode = mode.lower().strip()

    storage_path = os.getenv("VECTOR_STORE_STORAGE_PATH") or get_default_vector_storage_path()

    if provider == "qdrant":
        url = os.getenv("VECTOR_STORE_URL") or os.getenv("QDRANT_URL") or ""
    elif provider in ("chroma", "chromadb"):
        url = os.getenv("VECTOR_STORE_URL") or os.getenv("CHROMA_URL") or ""
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

def _resolve_default_embedding_config(conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
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

