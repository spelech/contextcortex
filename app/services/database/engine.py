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
    """Dynamically resolves SQLite path respecting module attribute, function, and env overrides."""
    env_path = os.getenv("CACHE_DB_PATH")
    conn_mod = sys.modules.get("app.services.database.connection")
    initial_default = getattr(conn_mod, "_INITIAL_CACHE_DB_PATH", None) if conn_mod else None
    conn_val = getattr(conn_mod, "CACHE_DB_PATH", None) if conn_mod else None
    db_mod = sys.modules.get("app.services.database")
    db_val = getattr(db_mod, "CACHE_DB_PATH", None) if db_mod else None

    if conn_val and db_val and conn_val != db_val:
        if conn_val != env_path and conn_val != initial_default:
            return conn_val
        if db_val != env_path and db_val != initial_default:
            return db_val
    if conn_val and conn_val != initial_default and conn_val != env_path:
        return conn_val
    if db_val and db_val != initial_default and db_val != env_path:
        return db_val
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
            connect_args={"check_same_thread": False, "timeout": 15.0},
            pool_pre_ping=True,
            **kwargs,
        )

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, connection_record):
            if isinstance(dbapi_connection, sqlite3.Connection):
                cursor = dbapi_connection.cursor()
                try:
                    cursor.execute("PRAGMA busy_timeout=15000;")
                except Exception as e:
                    logger.debug(f"Failed to set busy_timeout: {e}")
                try:
                    cursor.execute("PRAGMA journal_mode=WAL;")
                except Exception as e:
                    logger.debug(f"Failed to set journal_mode WAL: {e}")
                try:
                    cursor.execute("PRAGMA foreign_keys=ON;")
                except Exception as e:
                    logger.debug(f"Failed to set foreign_keys ON: {e}")
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
        if _GLOBAL_ENGINE is not None and _GLOBAL_ENGINE_URL != url:
            try:
                _GLOBAL_ENGINE.dispose()
            except Exception:
                pass
        _GLOBAL_ENGINE = engine
        _GLOBAL_ENGINE_URL = url

    return engine


def dispose_global_engine() -> None:
    """Disposes cached global database engine and clears references."""
    global _GLOBAL_ENGINE, _GLOBAL_ENGINE_URL
    if _GLOBAL_ENGINE is not None:
        try:
            _GLOBAL_ENGINE.dispose()
        except Exception:
            pass
        _GLOBAL_ENGINE = None
        _GLOBAL_ENGINE_URL = None


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
                ("openai_api_url", emb_cfg["litellm_url"]),
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


def _normalize_stored_paths(engine: Engine) -> None:
    """Normalizes any legacy Windows backslashes ('\\') in repository-scoped filepaths to POSIX slashes ('/')."""
    try:
        with engine.connect() as conn:
            for tbl, col in [
                ("indexed_files", "filepath"),
                ("ast_symbols", "filepath"),
                ("ast_relationships", "source_filepath"),
                ("api_routes", "filepath"),
                ("api_client_calls", "filepath"),
                ("file_summaries", "filepath"),
            ]:
                try:
                    conn.execute(
                        text(
                            f"UPDATE {tbl} SET {col} = REPLACE({col}, '\\\\', '/') "
                            f"WHERE {col} LIKE '%://%' AND INSTR({col}, '\\\\') > 0"
                            if not is_postgres(engine=engine)
                            else f"UPDATE {tbl} SET {col} = REPLACE({col}, '\\', '/') "
                            f"WHERE {col} LIKE '%://%' AND POSITION('\\' IN {col}) > 0"
                        )
                    )
                except Exception:
                    pass
            try:
                conn.execute(
                    text(
                        "UPDATE file_summaries SET folder = REPLACE(folder, '\\\\', '/') WHERE INSTR(folder, '\\\\') > 0"
                        if not is_postgres(engine=engine)
                        else "UPDATE file_summaries SET folder = REPLACE(folder, '\\', '/') WHERE POSITION('\\' IN folder) > 0"
                    )
                )
            except Exception:
                pass
            conn.commit()
    except Exception as e:
        logger.debug(f"Path normalization check skipped: {e}")


def _deduplicate_ast_and_routes(engine: Engine) -> None:
    """Purges duplicate rows in ast_symbols, ast_relationships, api_routes, and api_client_calls caused by prior re-indexing."""
    try:
        with engine.connect() as conn:
            index_queries = [
                "CREATE INDEX IF NOT EXISTS idx_ast_rel_source_symbol_id ON ast_relationships(source_symbol_id)",
                "CREATE INDEX IF NOT EXISTS idx_ast_rel_source_filepath ON ast_relationships(source_filepath)",
                "CREATE INDEX IF NOT EXISTS idx_ast_symbols_filepath ON ast_symbols(filepath)",
                "CREATE INDEX IF NOT EXISTS idx_api_routes_filepath ON api_routes(filepath)",
                "CREATE INDEX IF NOT EXISTS idx_api_calls_filepath ON api_client_calls(filepath)",
            ]
            for iq in index_queries:
                try:
                    conn.execute(text(iq))
                except Exception:
                    pass
            conn.commit()

            dedup_queries = [
                """
                DELETE FROM ast_relationships
                WHERE id IN (
                    SELECT id FROM (
                        SELECT id, ROW_NUMBER() OVER (
                            PARTITION BY COALESCE(repo, ''), COALESCE(source_filepath, ''), COALESCE(source_symbol, ''), COALESCE(target_symbol, ''), COALESCE(relationship_type, ''), COALESCE(line_number, 0)
                            ORDER BY id
                        ) AS rn
                        FROM ast_relationships
                    ) dedup_sub WHERE rn > 1
                )
                """,
                """
                DELETE FROM ast_symbols
                WHERE id IN (
                    SELECT id FROM (
                        SELECT id, ROW_NUMBER() OVER (
                            PARTITION BY COALESCE(repo, ''), COALESCE(filepath, ''), COALESCE(name, ''), COALESCE(full_symbol, ''), COALESCE(kind, ''), COALESCE(start_line, 0), COALESCE(end_line, 0)
                            ORDER BY id
                        ) AS rn
                        FROM ast_symbols
                    ) dedup_sub WHERE rn > 1
                )
                """,
                """
                DELETE FROM api_routes
                WHERE id IN (
                    SELECT id FROM (
                        SELECT id, ROW_NUMBER() OVER (
                            PARTITION BY COALESCE(repo, ''), COALESCE(filepath, ''), COALESCE(framework, ''), COALESCE(http_method, ''), COALESCE(path_pattern, ''), COALESCE(handler_symbol, ''), COALESCE(start_line, 0)
                            ORDER BY id
                        ) AS rn
                        FROM api_routes
                    ) dedup_sub WHERE rn > 1
                )
                """,
                """
                DELETE FROM api_client_calls
                WHERE id IN (
                    SELECT id FROM (
                        SELECT id, ROW_NUMBER() OVER (
                            PARTITION BY COALESCE(repo, ''), COALESCE(filepath, ''), COALESCE(http_method, ''), COALESCE(url_pattern, ''), COALESCE(caller_symbol, ''), COALESCE(line_number, 0)
                            ORDER BY id
                        ) AS rn
                        FROM api_client_calls
                    ) dedup_sub WHERE rn > 1
                )
                """,
            ]
            cleanup_queries = [
                "DELETE FROM ast_symbols WHERE name = 'anonymous'",
                "DELETE FROM indexed_files WHERE filepath LIKE '%://www/assets/%' OR filepath LIKE '%://wwwroot/_framework/%' OR filepath LIKE '%://wwwroot/lib/%' OR filepath LIKE '%.min.js' OR filepath LIKE '%.min.css'",
                "DELETE FROM ast_symbols WHERE filepath LIKE '%://www/assets/%' OR filepath LIKE '%://wwwroot/_framework/%' OR filepath LIKE '%://wwwroot/lib/%' OR filepath LIKE '%.min.js' OR filepath LIKE '%.min.css'",
                "DELETE FROM ast_relationships WHERE source_filepath LIKE '%://www/assets/%' OR source_filepath LIKE '%://wwwroot/_framework/%' OR source_filepath LIKE '%://wwwroot/lib/%' OR source_filepath LIKE '%.min.js' OR source_filepath LIKE '%.min.css'",
                "DELETE FROM file_summaries WHERE filepath LIKE '%://www/assets/%' OR filepath LIKE '%://wwwroot/_framework/%' OR filepath LIKE '%://wwwroot/lib/%' OR filepath LIKE '%.min.js' OR filepath LIKE '%.min.css'",
            ]
            for cq in cleanup_queries:
                try:
                    conn.execute(text(cq))
                except Exception:
                    pass

            for q in dedup_queries:
                try:
                    conn.execute(text(q))
                except Exception:
                    pass
            conn.commit()
    except Exception as e:
        logger.debug(f"Deduplication check skipped: {e}")


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

    try:
        from app.services.database.connection import ensure_file_summaries_columns
        with eng.connect() as conn:
            ensure_file_summaries_columns(conn)
    except Exception as me:
        logger.debug(f"Column migration check: {me}")

    _normalize_stored_paths(eng)
    _deduplicate_ast_and_routes(eng)

    # Seed default data
    _seed_defaults(eng, vault_path=vault_path)

    return eng

