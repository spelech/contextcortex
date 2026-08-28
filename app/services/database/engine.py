"""
SQLAlchemy 2.0 Database Engine Factory and Connection Manager.
Provides unified connection pooling, schema migration/creation,
resilient startup retry loops, and transaction management across SQLite and PostgreSQL.
"""

import os
import sys
import json
import time
import logging
import sqlite3
from typing import Optional, Dict, Any
from contextlib import contextmanager

from sqlalchemy import create_engine, Engine, text, select, func, event
from sqlalchemy.exc import OperationalError, DatabaseError

from app.services.database.schema import metadata, TABLES

logger = logging.getLogger("contextcortex.db.engine")

_GLOBAL_ENGINE: Optional[Engine] = None
_GLOBAL_ENGINE_URL: Optional[str] = None


def get_default_db_path() -> str:
    env_path = os.getenv("CACHE_DB_PATH")
    if env_path:
        return env_path
    if os.path.exists("/app") and os.access("/app", os.W_OK):
        return "/app/data/index_cache.db"
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "data",
        "index_cache.db",
    )


def get_current_db_path() -> str:
    """Dynamically resolves SQLite path respecting module attribute overrides."""
    db_mod = sys.modules.get("app.services.database")
    if db_mod and hasattr(db_mod, "CACHE_DB_PATH") and db_mod.CACHE_DB_PATH:
        return db_mod.CACHE_DB_PATH
    conn_mod = sys.modules.get("app.services.database.connection")
    if conn_mod and hasattr(conn_mod, "CACHE_DB_PATH") and conn_mod.CACHE_DB_PATH:
        return conn_mod.CACHE_DB_PATH
    return get_default_db_path()


def get_db_url(database_url: Optional[str] = None) -> str:
    """
    Resolves and normalizes the target database URL.
    Converts postgresql:// to postgresql+psycopg:// to ensure psycopg3 driver is used.
    """
    url = database_url or os.getenv("DATABASE_URL")
    if not url:
        db_path = get_current_db_path()
        try:
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
        except Exception:
            pass
        return f"sqlite:///{db_path}"

    url = url.strip()
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]

    return url


def is_postgres(database_url: Optional[str] = None, engine: Optional[Engine] = None) -> bool:
    """Returns True if the specified database URL or engine uses PostgreSQL."""
    if engine is not None:
        return engine.dialect.name == "postgresql"
    url = get_db_url(database_url)
    return url.startswith("postgresql") or "postgres" in url


def get_db_engine(database_url: Optional[str] = None, reset: bool = False, **kwargs) -> Engine:
    """
    Returns a cached SQLAlchemy Engine instance or creates a new one for the given URL.
    """
    global _GLOBAL_ENGINE, _GLOBAL_ENGINE_URL

    url = get_db_url(database_url)

    if not reset and _GLOBAL_ENGINE is not None and _GLOBAL_ENGINE_URL == url and not kwargs:
        return _GLOBAL_ENGINE

    if url.startswith("sqlite"):
        engine = create_engine(
            url,
            connect_args={"check_same_thread": False},
            pool_pre_ping=True,
            **kwargs,
        )

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, connection_record):
            if isinstance(dbapi_connection, sqlite3.Connection):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL;")
                cursor.execute("PRAGMA busy_timeout=5000;")
                cursor.execute("PRAGMA foreign_keys=ON;")
                cursor.close()

    else:
        engine = create_engine(
            url,
            pool_pre_ping=True,
            pool_size=kwargs.get("pool_size", 10),
            max_overflow=kwargs.get("max_overflow", 20),
            **{k: v for k, v in kwargs.items() if k not in ("pool_size", "max_overflow")},
        )

    if database_url is None or database_url == os.getenv("DATABASE_URL"):
        _GLOBAL_ENGINE = engine
        _GLOBAL_ENGINE_URL = url

    return engine


@contextmanager
def get_connection(engine: Optional[Engine] = None):
    """
    Context manager that yields an active SQLAlchemy Connection.
    """
    eng = engine or get_db_engine()
    with eng.connect() as conn:
        yield conn


def wait_for_db(
    engine: Optional[Engine] = None,
    max_retries: int = 15,
    initial_delay: float = 1.0,
    max_delay: float = 5.0,
) -> bool:
    """
    Resilient startup retry loop for container cold boots.
    Attempts to establish a connection with exponential backoff up to ~30s.
    """
    eng = engine or get_db_engine()
    delay = initial_delay

    for attempt in range(1, max_retries + 1):
        try:
            with eng.connect() as conn:
                conn.execute(text("SELECT 1"))
                logger.info(f"Database connection established successfully on attempt {attempt}.")
                return True
        except (OperationalError, DatabaseError, Exception) as exc:
            if attempt == max_retries:
                logger.error(f"Database connection failed after {max_retries} attempts: {exc}")
                raise
            logger.warning(
                f"Database connection attempt {attempt}/{max_retries} failed: {exc}. Retrying in {delay:.2f}s..."
            )
            time.sleep(delay)
            delay = min(max_delay, delay * 1.5)

    return False


def _seed_defaults(engine: Engine, vault_path: str = "/docs") -> None:
    """Seeds initial system metadata, default prompts, and vault path."""
    with engine.connect() as conn:
        # 1. Default custom prompts
        try:
            prompt_count = conn.execute(
                select(func.count()).select_from(TABLES["custom_prompts"])
            ).scalar() or 0

            if prompt_count == 0:
                default_prompts = [
                    {
                        "name": "search_infrastructure_docs",
                        "description": "Workflow to search system infrastructure documentation, container mappings, or network routes.",
                        "arguments_json": json.dumps([
                            {"name": "topic", "description": "The specific infrastructure topic to search for", "required": True}
                        ]),
                        "template": "Please perform a search using the search_docs tool for topic '{topic}' and summarize the matching container mappings, port numbers, reverse proxy routes, or setup instructions.",
                    },
                    {
                        "name": "find_implementation_symbol",
                        "description": "Workflow to locate functions, classes, and logic across registered codebases.",
                        "arguments_json": json.dumps([
                            {"name": "symbol", "description": "Function or class name to find", "required": True},
                            {"name": "repo", "description": "Target repository (optional)", "required": False},
                        ]),
                        "template": "Please use find_symbol for '{symbol}' in repo '{repo}' and inspect its declaration, line numbers, and implementation details.",
                    },
                ]
                conn.execute(TABLES["custom_prompts"].insert(), default_prompts)
                conn.commit()
        except Exception as pe:
            logger.error(f"Failed to seed default prompts: {pe}")

        # 2. Vault path
        try:
            conn.execute(
                TABLES["indexed_paths"].delete().where(TABLES["indexed_paths"].c.path == "/notes")
            )
            conn.commit()

            path_count = conn.execute(
                select(func.count()).select_from(TABLES["indexed_paths"])
            ).scalar() or 0

            if path_count == 0 and os.path.exists(vault_path):
                conn.execute(
                    TABLES["indexed_paths"].insert().values(
                        path=os.path.abspath(vault_path),
                        type="directory",
                        recursive=1,
                        enabled=1,
                        category="default",
                        repo="vault",
                    )
                )
                conn.commit()
        except Exception as se:
            logger.error(f"Failed to seed default vault path: {se}")

        # 3. Vector store defaults
        try:
            from app.services.database.connection import _resolve_default_vector_store_config
            default_cfg = _resolve_default_vector_store_config()
            for key, val in [
                ("vector_store_provider", default_cfg["provider"]),
                ("vector_store_mode", default_cfg["mode"]),
                ("vector_store_storage_path", default_cfg["storage_path"]),
                ("vector_store_url", default_cfg["url"]),
                ("vector_store_collection", default_cfg["collection"]),
            ]:
                existing = conn.execute(
                    select(TABLES["system_metadata"].c.value).where(TABLES["system_metadata"].c.key == key)
                ).scalar()
                if existing is None:
                    conn.execute(TABLES["system_metadata"].insert().values(key=key, value=str(val)))
            conn.commit()
        except Exception as ve:
            logger.error(f"Failed to seed vector store configuration: {ve}")

        # 4. Embedding defaults
        try:
            from app.services.database.connection import _resolve_default_embedding_config
            emb_cfg = _resolve_default_embedding_config()
            for key, val in [
                ("embedding_provider", emb_cfg["provider"]),
                ("embedding_dense_model", emb_cfg["dense_model"]),
                ("embedding_sparse_model", emb_cfg["sparse_model"]),
                ("embedding_num_threads", str(emb_cfg["threads"])),
                ("embedding_batch_size", str(emb_cfg["batch_size"])),
                ("embedding_litellm_url", emb_cfg["litellm_url"]),
            ]:
                existing = conn.execute(
                    select(TABLES["system_metadata"].c.value).where(TABLES["system_metadata"].c.key == key)
                ).scalar()
                if existing is None:
                    conn.execute(TABLES["system_metadata"].insert().values(key=key, value=str(val)))
            conn.commit()
        except Exception as ee:
            logger.error(f"Failed to seed embedding configuration: {ee}")


def init_db(vault_path: str = "/docs", engine: Optional[Engine] = None) -> Engine:
    """
    Initializes database schema and default seeds.
    For PostgreSQL: waits for connection, activates vector extension if available,
    and runs metadata.create_all(bind=engine).
    """
    eng = engine or get_db_engine()

    if is_postgres(engine=eng):
        wait_for_db(engine=eng)
        try:
            with eng.connect() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
                conn.commit()
        except Exception as e:
            logger.warning(f"Could not enable 'vector' extension automatically (might require superuser): {e}")

    # Create all defined tables idempotently
    metadata.create_all(bind=eng)

    # Seed default data
    _seed_defaults(eng, vault_path=vault_path)

    return eng
