"""PostgreSQL pgvector schema initialization, FTS column migration, and online index creation."""

import logging
import threading
import time
from typing import Optional, Tuple
from sqlalchemy import Engine, text

logger = logging.getLogger("contextcortex.vector_store.pgvector")

_FTS_EXPR = (
    "to_tsvector('simple', COALESCE(title, '') || ' ' || COALESCE(symbol, '') "
    "|| ' ' || COALESCE(path, '') || ' ' || COALESCE(content, ''))"
)
_CONCURRENT_LOCK_TIMEOUT = "60s"
_CONCURRENT_WAIT_WARN_SECONDS = 60.0


def _set_migration_status(message: Optional[str]) -> None:
    try:
        from app.services.vector_store.manager import VectorStoreManager
        VectorStoreManager.set_migration_status(message)
    except Exception:
        pass


def _get_index_info(engine: Engine, table_name: str, index_name: str) -> Tuple[Optional[str], bool]:
    """Returns `(indexdef, is_valid)` on a short-lived connection with no open transaction left behind."""
    sql = text("""
        SELECT i.indexdef, COALESCE(pgi.indisvalid, TRUE) AS is_valid
        FROM pg_indexes i
        LEFT JOIN pg_class c ON c.relname = i.indexname
        LEFT JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = i.schemaname
        LEFT JOIN pg_index pgi ON pgi.indexrelid = c.oid
        WHERE i.tablename = :t AND i.indexname = :idx
        LIMIT 1
    """)
    with engine.connect() as conn:
        result = conn.execute(sql, {"t": table_name, "idx": index_name})
        row = result.fetchone()
        try:
            conn.rollback()
        except Exception:
            pass
    if row is not None:
        idx_def = row[0] if len(row) >= 1 else None
        is_valid = bool(row[1]) if len(row) >= 2 and row[1] is not None else True
        if isinstance(idx_def, str):
            return idx_def, is_valid
        return None, True
    # Compatibility fallback for unit-test mocks that only stub `.scalar()`.
    val = result.scalar() if hasattr(result, "scalar") else None
    if isinstance(val, str):
        return val, True
    return None, True


def _log_blocking_activity(engine: Engine, index_name: str, elapsed: float) -> None:
    """Logs blocking PostgreSQL backends if a concurrent index build waits longer than expected."""
    blockers = ""
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT pid, state, LEFT(query, 120) FROM pg_stat_activity "
                "WHERE pid <> pg_backend_pid() AND state IS NOT NULL AND state <> 'idle' "
                "ORDER BY xact_start ASC NULLS LAST LIMIT 5"
            )).fetchall()
            try:
                conn.rollback()
            except Exception:
                pass
        if rows:
            blockers = "; active backends: " + ", ".join(f"pid={r[0]} ({r[1]}: {r[2]})" for r in rows)
    except Exception:
        pass
    logger.warning(
        "Concurrent index DDL for '%s' has been waiting for %.0fs%s",
        index_name, elapsed, blockers,
    )


def _run_autocommit_ddl(engine: Engine, sql: str, index_name: str = "") -> bool:
    """Executes DDL (such as CREATE/DROP INDEX CONCURRENTLY) on an AUTOCOMMIT connection with NO open transaction."""
    stop_event = threading.Event()
    t0 = time.perf_counter()

    def _watchdog() -> None:
        while not stop_event.wait(timeout=_CONCURRENT_WAIT_WARN_SECONDS):
            _log_blocking_activity(engine, index_name or sql[:40], time.perf_counter() - t0)

    watcher = threading.Thread(target=_watchdog, name="cc-pg-ddl-watchdog", daemon=True)
    watcher.start()
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as auto_conn:
            try:
                auto_conn.execute(text(f"SET lock_timeout = '{_CONCURRENT_LOCK_TIMEOUT}'"))
            except Exception:
                pass
            auto_conn.execute(text(sql))
        return True
    except Exception as exc:
        logger.debug("Autocommit DDL failed (%s); falling back to transactional DDL: %s", sql[:80], exc)
        return False
    finally:
        stop_event.set()
        watcher.join(timeout=0.5)


def _run_transactional_ddl(engine: Engine, sql: str) -> None:
    """Executes standard DDL inside its own short-lived transaction (only used when CONCURRENTLY is not used/available)."""
    with engine.connect() as conn, conn.begin():
        conn.execute(text(sql))


def _drop_index(engine: Engine, index_name: str, has_rows: bool) -> None:
    if has_rows and _run_autocommit_ddl(engine, f"DROP INDEX CONCURRENTLY IF EXISTS {index_name};", index_name):
        return
    _run_transactional_ddl(engine, f"DROP INDEX IF EXISTS {index_name};")


def _ensure_index(
    engine: Engine,
    table_name: str,
    index_name: str,
    create_body: str,
    has_rows: bool,
    migration_label: Optional[str] = None,
) -> None:
    """Creates an index if missing or INVALID, preferring CONCURRENTLY on populated tables with zero open transactions."""
    existing_def, is_valid = _get_index_info(engine, table_name, index_name)
    if existing_def is not None and is_valid:
        return
    if existing_def is not None and not is_valid:
        logger.warning("Found INVALID index '%s' on '%s' (likely from an interrupted concurrent build); dropping and rebuilding.", index_name, table_name)
        _drop_index(engine, index_name, has_rows=has_rows)

    t0 = time.perf_counter()
    if has_rows and migration_label:
        _set_migration_status(migration_label)
        logger.info("%s", migration_label)
    if has_rows:
        concurrent_sql = f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {index_name} ON {table_name} {create_body};"
        if _run_autocommit_ddl(engine, concurrent_sql, index_name):
            if migration_label:
                logger.info("Finished building index '%s' on '%s' in %.1fs.", index_name, table_name, time.perf_counter() - t0)
            return
    _run_transactional_ddl(engine, f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} {create_body};")
    if has_rows and migration_label:
        logger.info("Finished building index '%s' on '%s' in %.1fs.", index_name, table_name, time.perf_counter() - t0)


def _migrate_fts_index(engine: Engine, table_name: str, has_rows: bool) -> None:
    """Ensures a valid GIN index on stored `fts`; builds replacement before dropping legacy expression index."""
    idx_name = f"idx_{table_name}_fts"
    existing_def, is_valid = _get_index_info(engine, table_name, idx_name)
    is_legacy_expr = bool(existing_def and "to_tsvector(" in existing_def.lower())

    if is_legacy_expr:
        temp_idx = f"idx_{table_name}_fts_stored"
        label = f"Building GIN FTS index on '{table_name}' (one-time migration; keeping existing index until ready)..."
        _ensure_index(engine, table_name, temp_idx, "USING gin (fts)", has_rows=has_rows, migration_label=label)
        _drop_index(engine, idx_name, has_rows=has_rows)
        if not (has_rows and _run_autocommit_ddl(engine, f"ALTER INDEX IF EXISTS {temp_idx} RENAME TO {idx_name};", temp_idx)):
            _run_transactional_ddl(engine, f"ALTER INDEX IF EXISTS {temp_idx} RENAME TO {idx_name};")
        return

    if existing_def is not None and not is_valid:
        logger.warning("Found INVALID FTS index '%s' on '%s'; dropping and rebuilding.", idx_name, table_name)
        _drop_index(engine, idx_name, has_rows=has_rows)

    label = f"Building GIN FTS index on '{table_name}' (one-time migration)..." if has_rows else None
    _ensure_index(engine, table_name, idx_name, "USING gin (fts)", has_rows=has_rows, migration_label=label)


def ensure_pgvector_collection(engine: Engine, table_name: str, dimension: int) -> bool:
    """Initializes vector extension, documents table schema, and HNSW/GIN/B-tree indexes idempotently."""
    try:
        is_sqlite = getattr(engine.dialect, "name", "") == "sqlite"
        has_rows = False

        with engine.connect() as conn, conn.begin():
            if not is_sqlite:
                extension = conn.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")).scalar()
                if not extension:
                    conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))

                check_dim_sql = text("""
                    SELECT atttypmod FROM pg_attribute
                    WHERE attrelid = to_regclass(:table_name) AND attname = 'embedding';
                """)
                row = conn.execute(check_dim_sql, {"table_name": table_name}).fetchone()
                if row and row[0] is not None and row[0] > 0 and row[0] != dimension:
                    conn.execute(text(f"LOCK TABLE {table_name} IN ACCESS EXCLUSIVE MODE"))
                    if conn.execute(text(f"SELECT EXISTS (SELECT 1 FROM {table_name})")).scalar():
                        raise ValueError(
                            f"Vector dimension mismatch for table '{table_name}': "
                            f"existing {row[0]}d, configured {dimension}d. "
                            "An explicit rebuild is required; all collections sharing this "
                            "table must be cleared before changing dimensions."
                        )
                    conn.execute(text(
                        f"ALTER TABLE {table_name} ALTER COLUMN embedding TYPE vector({dimension})"
                    ))

            fts_col_ddl = "" if is_sqlite else f"fts tsvector GENERATED ALWAYS AS ({_FTS_EXPR}) STORED,\n                    "
            create_table_sql = f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                id VARCHAR(255), collection_name VARCHAR(255) DEFAULT 'knowledge_rag_v1',
                repo VARCHAR(255), doc_type VARCHAR(50) DEFAULT 'doc',
                path TEXT, rel_path TEXT, title TEXT, folder TEXT, category TEXT,
                tags JSONB, heading TEXT, symbol TEXT, language VARCHAR(50),
                start_line INTEGER, end_line INTEGER, github_url TEXT, permalink_url TEXT,
                content TEXT,
                embedding {"TEXT" if is_sqlite else "vector(" + str(dimension) + ")"},
                {fts_col_ddl}payload JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (collection_name, id)
            );
            """
            conn.execute(text(create_table_sql))

            if not is_sqlite:
                has_rows = bool(conn.execute(text(f"SELECT EXISTS (SELECT 1 FROM {table_name})")).scalar())

                has_coll = conn.execute(
                    text("SELECT 1 FROM pg_attribute WHERE attrelid = to_regclass(:t) AND attname = 'collection_name' AND NOT attisdropped"),
                    {"t": table_name},
                ).scalar()
                if not has_coll:
                    conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS collection_name VARCHAR(255) DEFAULT 'knowledge_rag_v1';"))
                    conn.execute(text(f"UPDATE {table_name} SET collection_name = 'knowledge_rag_v1' WHERE collection_name IS NULL;"))

                has_fts = conn.execute(
                    text("SELECT 1 FROM pg_attribute WHERE attrelid = to_regclass(:t) AND attname = 'fts' AND NOT attisdropped"),
                    {"t": table_name},
                ).scalar()
                if not has_fts:
                    t_fts = time.perf_counter()
                    msg = (
                        f"Adding stored FTS column to '{table_name}' "
                        "(one-time migration; can take a few minutes on a large index)..."
                    )
                    _set_migration_status(msg)
                    logger.info("%s", msg)
                    conn.execute(text(
                        f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS fts tsvector "
                        f"GENERATED ALWAYS AS ({_FTS_EXPR}) STORED;"
                    ))
                    logger.info(
                        "Finished adding stored FTS column to '%s' in %.1fs.",
                        table_name, time.perf_counter() - t_fts,
                    )

                pk_check_sql = text("""
                    SELECT a.attname
                    FROM pg_index i
                    JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                    WHERE i.indrelid = CAST(:table_name AS regclass) AND i.indisprimary;
                """)
                pk_cols = [r[0] for r in conn.execute(pk_check_sql, {"table_name": table_name}).fetchall()]
                if set(pk_cols) != {"collection_name", "id"}:
                    if pk_cols:
                        conname_row = conn.execute(
                            text("SELECT conname FROM pg_constraint WHERE conrelid = CAST(:table_name AS regclass) AND contype = 'p';"),
                            {"table_name": table_name},
                        ).fetchone()
                        if conname_row:
                            conname = engine.dialect.identifier_preparer.quote(conname_row[0])
                            conn.execute(text(f"ALTER TABLE {table_name} DROP CONSTRAINT {conname};"))
                    conn.execute(text(f"ALTER TABLE {table_name} ADD PRIMARY KEY (collection_name, id);"))

        # The table/column transaction above is now committed and closed so CONCURRENTLY DDL cannot self-deadlock.
        if not is_sqlite:
            _ensure_index(
                engine, table_name,
                f"idx_{table_name}_embedding", "USING hnsw (embedding vector_cosine_ops)",
                has_rows=has_rows,
                migration_label=f"Building HNSW embedding index on '{table_name}'...",
            )
            _migrate_fts_index(engine, table_name, has_rows=has_rows)
            _ensure_index(
                engine, table_name,
                f"idx_{table_name}_coll_repo_rel_path", "(collection_name, repo, rel_path)",
                has_rows=has_rows,
                migration_label=f"Building file-lookup index on '{table_name}' (collection_name, repo, rel_path)...",
            )
            for suffix, cols in (
                ("collection", "(collection_name)"),
                ("repo", "(repo)"),
                ("type", "(doc_type)"),
                ("path", "(path)"),
            ):
                _ensure_index(engine, table_name, f"idx_{table_name}_{suffix}", cols, has_rows=False)

        logger.info("PgVectorStore initialized table '%s' with %dd HNSW, GIN FTS, and file-lookup indexes.", table_name, dimension)
        return True
    except ValueError:
        raise
    except Exception as e:
        logger.error("Error initializing PgVectorStore table '%s': %s", table_name, e, exc_info=True)
        raise RuntimeError(f"Failed to initialize PgVectorStore table '{table_name}'.") from e
    finally:
        _set_migration_status(None)
