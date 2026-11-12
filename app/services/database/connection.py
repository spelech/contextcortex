import logging
import os
import sqlite3
import sys
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import func, select, text

from app.services.database.engine import (
    get_connection,
    get_current_db_path,
    get_db_engine,
    get_default_db_path,
    init_db as engine_init_db,
    is_postgres,
)
from app.services.database.postgres_compat import (
    DictRow,
    PostgresConnectionAdapter,
    PostgresCursorAdapter,
    PostgresResultAdapter,
    TABLES_WITH_ID,
    _SingleRowResult,
    _convert_sql_placeholders,
)
from app.services.database.schema import TABLES

logger = logging.getLogger("contextcortex.db")

_INITIAL_CACHE_DB_PATH = get_default_db_path()
CACHE_DB_PATH = _INITIAL_CACHE_DB_PATH
if not is_postgres():
    try:
        os.makedirs(os.path.dirname(CACHE_DB_PATH), exist_ok=True)
    except Exception:
        pass


def _resolve_sqlite_db_path() -> str:
    """Resolves active SQLite path via unified engine resolution so SQLAlchemy and sqlite3 never diverge."""
    return get_current_db_path()


def get_db_connection() -> Any:
    """Returns a database connection (PostgreSQL adapter or SQLite connection) based on active database selection."""
    if is_postgres():
        return PostgresConnectionAdapter()

    db_path = _resolve_sqlite_db_path()
    try:
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
    except Exception:
        pass

    conn = sqlite3.connect(db_path, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=15000;")
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db(vault_path: str = "/docs", engine=None):
    """Initializes database schema and seed data via SQLAlchemy Core engine."""
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


def set_metadata(key: str, value: str) -> None:
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


def ensure_git_repositories_columns(conn=None) -> None:
    """Ensures keep_shallow and retain_commits_count columns exist on git_repositories table."""
    try:
        if is_postgres():
            with get_connection() as sa_conn:
                res = sa_conn.execute(
                    text("SELECT column_name FROM information_schema.columns WHERE table_name='git_repositories' AND column_name='keep_shallow'")
                ).fetchone()
                if not res:
                    sa_conn.execute(text("ALTER TABLE git_repositories ADD COLUMN keep_shallow INTEGER DEFAULT 0"))
                    sa_conn.commit()
                    logger.info("Migrated git_repositories: added keep_shallow column")

                res_retain = sa_conn.execute(
                    text("SELECT column_name FROM information_schema.columns WHERE table_name='git_repositories' AND column_name='retain_commits_count'")
                ).fetchone()
                if not res_retain:
                    sa_conn.execute(text("ALTER TABLE git_repositories ADD COLUMN retain_commits_count INTEGER DEFAULT 20"))
                    sa_conn.commit()
                    logger.info("Migrated git_repositories: added retain_commits_count column")
        else:
            raw_conn = get_db_connection()
            try:
                cols = [r["name"] for r in raw_conn.execute("PRAGMA table_info(git_repositories)").fetchall()]
                if cols and "keep_shallow" not in cols:
                    raw_conn.execute("ALTER TABLE git_repositories ADD COLUMN keep_shallow INTEGER DEFAULT 0")
                    raw_conn.commit()
                    logger.info("Migrated git_repositories: added keep_shallow column")
                if cols and "retain_commits_count" not in cols:
                    raw_conn.execute("ALTER TABLE git_repositories ADD COLUMN retain_commits_count INTEGER DEFAULT 20")
                    raw_conn.commit()
                    logger.info("Migrated git_repositories: added retain_commits_count column")
            finally:
                raw_conn.close()
    except Exception as e:
        logger.debug(f"Migration error for git_repositories: {e}")


def ensure_file_summaries_columns(conn=None) -> None:
    """Ensures summary_text column exists on file_summaries and git_repositories columns are migrated."""
    try:
        ensure_git_repositories_columns(conn)
        if is_postgres():
            with get_connection() as sa_conn:
                res = sa_conn.execute(
                    text("SELECT column_name FROM information_schema.columns WHERE table_name='file_summaries' AND column_name='summary_text'")
                ).fetchone()
                if not res:
                    sa_conn.execute(text("ALTER TABLE file_summaries ADD COLUMN summary_text TEXT"))
                    sa_conn.commit()
        else:
            raw_conn = get_db_connection()
            try:
                cols = [r["name"] for r in raw_conn.execute("PRAGMA table_info(file_summaries)").fetchall()]
                if cols and "summary_text" not in cols:
                    raw_conn.execute("ALTER TABLE file_summaries ADD COLUMN summary_text TEXT")
                    raw_conn.commit()
            finally:
                raw_conn.close()
    except Exception as e:
        logger.debug(f"Migration error for file_summaries: {e}")


def check_db_readiness() -> Tuple[bool, Dict[str, Any]]:
    """Verifies database engine connectivity and core relational schema readability."""
    db_type = "postgresql" if is_postgres() else "sqlite"
    required_tables = [
        "system_metadata",
        "git_repositories",
        "indexed_paths",
        "indexed_files",
        "ast_symbols",
        "file_summaries",
    ]

    try:
        with get_connection() as conn:
            for table_name in required_tables:
                if table_name in TABLES:
                    conn.execute(select(func.count()).select_from(TABLES[table_name])).scalar()

        if is_postgres():
            with get_connection() as raw_conn:
                for table_name in required_tables:
                    raw_conn.execute(text(f"SELECT 1 FROM {table_name} LIMIT 1"))
        else:
            with get_db_connection() as raw_conn:
                cursor = raw_conn.cursor()
                for table_name in required_tables:
                    cursor.execute(f"SELECT 1 FROM {table_name} LIMIT 1")

        return True, {"status": "ok", "type": db_type}
    except Exception as e:
        logger.warning(f"Database readiness check failed ({db_type}): {e}")
        return False, {"status": "error", "type": db_type}


def clear_indexing_metadata() -> None:
    """Clears relational index tables and resets git repository sync markers."""
    with get_db_connection() as conn:
        for table in (
            "indexed_files",
            "file_summaries",
            "ast_symbols",
            "ast_relationships",
            "api_routes",
            "api_client_calls",
            "embedding_cache",
            "git_commits",
        ):
            try:
                conn.execute(f"DELETE FROM {table}")
            except Exception as e:
                logger.debug(f"Error clearing table {table}: {e}")
        try:
            conn.execute("UPDATE git_repositories SET commit_sha = NULL, last_synced = NULL")
        except Exception as e:
            logger.debug(f"Error resetting git_repositories sync state: {e}")
        conn.commit()
    logger.info("Relational indexing metadata and embedding cache cleared.")


from app.services.database.config_store import (  # noqa: E402
    _PLACEHOLDER_API_KEYS,
    _is_placeholder_api_key,
    _resolve_default_embedding_config,
    _resolve_default_vector_store_config,
    detect_system_resources,
    get_ai_gateway_config,
    get_chat_model,
    get_default_vector_storage_path,
    get_embedding_db_config,
    get_file_settings,
    get_vector_store_db_config,
    get_vision_ocr_model,
    set_ai_gateway_config,
    set_embedding_db_config,
    set_file_settings,
    set_vector_store_db_config,
)

__all__ = [
    "CACHE_DB_PATH",
    "DictRow",
    "TABLES_WITH_ID",
    "_convert_sql_placeholders",
    "_SingleRowResult",
    "PostgresResultAdapter",
    "PostgresCursorAdapter",
    "PostgresConnectionAdapter",
    "get_default_db_path",
    "get_db_engine",
    "get_connection",
    "is_postgres",
    "get_db_connection",
    "init_db",
    "get_metadata",
    "set_metadata",
    "get_default_vector_storage_path",
    "_resolve_default_vector_store_config",
    "get_vector_store_db_config",
    "set_vector_store_db_config",
    "detect_system_resources",
    "_PLACEHOLDER_API_KEYS",
    "_is_placeholder_api_key",
    "_resolve_default_embedding_config",
    "get_embedding_db_config",
    "set_embedding_db_config",
    "get_vision_ocr_model",
    "get_chat_model",
    "get_ai_gateway_config",
    "set_ai_gateway_config",
    "ensure_git_repositories_columns",
    "ensure_file_summaries_columns",
    "check_db_readiness",
    "get_file_settings",
    "set_file_settings",
    "clear_indexing_metadata",
]
