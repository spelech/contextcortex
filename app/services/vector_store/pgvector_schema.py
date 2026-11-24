"""PostgreSQL pgvector schema initialization, FTS column migration, and online index creation."""

import logging
import time
from typing import Optional
from sqlalchemy import Engine, text

logger = logging.getLogger("contextcortex.vector_store.pgvector")

_FTS_EXPR = (
    "to_tsvector('simple', COALESCE(title, '') || ' ' || COALESCE(symbol, '') "
    "|| ' ' || COALESCE(path, '') || ' ' || COALESCE(content, ''))"
)


def _set_migration_status(message: Optional[str]) -> None:
    try:
        from app.services.vector_store.manager import VectorStoreManager
        VectorStoreManager.set_migration_status(message)
    except Exception:
        pass


def _get_index_def(conn, table_name: str, index_name: str) -> Optional[str]:
    val = conn.execute(
        text("SELECT indexdef FROM pg_indexes WHERE tablename = :t AND indexname = :idx"),
        {"t": table_name, "idx": index_name},
    ).scalar()
    return str(val) if isinstance(val, str) else None


def _run_autocommit_ddl(engine: Engine, sql: str) -> bool:
    """Executes DDL (such as CREATE/DROP INDEX CONCURRENTLY) outside a transaction block."""
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as auto_conn:
            auto_conn.execute(text(sql))
        return True
    except Exception as exc:
        logger.debug("Autocommit DDL failed (%s); falling back to transactional DDL: %s", sql[:80], exc)
        return False


def _ensure_index(
    engine: Engine,
    conn,
    table_name: str,
    index_name: str,
    create_body: str,
    has_rows: bool,
    migration_label: Optional[str] = None,
) -> None:
    """Creates an index if missing, preferring CONCURRENTLY on populated tables."""
    if _get_index_def(conn, table_name, index_name) is not None:
        return
    t0 = time.perf_counter()
    if has_rows and migration_label:
        _set_migration_status(migration_label)
        logger.info("%s", migration_label)
    if has_rows:
        concurrent_sql = f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {index_name} ON {table_name} {create_body};"
        if _run_autocommit_ddl(engine, concurrent_sql):
            if migration_label:
                logger.info("Finished building index '%s' on '%s' in %.1fs.", index_name, table_name, time.perf_counter() - t0)
            return
    conn.execute(text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} {create_body};"))
    if has_rows and migration_label:
        logger.info("Finished building index '%s' on '%s' in %.1fs.", index_name, table_name, time.perf_counter() - t0)


def _migrate_fts_index(engine: Engine, conn, table_name: str, has_rows: bool) -> None:
    """Ensures a GIN index on stored `fts`; builds replacement before dropping legacy expression index."""
    idx_name = f"idx_{table_name}_fts"
    existing_def = _get_index_def(conn, table_name, idx_name)
    is_legacy_expr = bool(existing_def and "to_tsvector(" in existing_def.lower())

    if is_legacy_expr:
        temp_idx = f"idx_{table_name}_fts_stored"
        label = f"Building GIN FTS index on '{table_name}' (one-time migration; keeping existing index until ready)..."
        _ensure_index(engine, conn, table_name, temp_idx, "USING gin (fts)", has_rows=has_rows, migration_label=label)
        if has_rows and _run_autocommit_ddl(engine, f"DROP INDEX CONCURRENTLY IF EXISTS {idx_name};"):
            _run_autocommit_ddl(engine, f"ALTER INDEX IF EXISTS {temp_idx} RENAME TO {idx_name};")
        else:
            conn.execute(text(f"DROP INDEX IF EXISTS {idx_name};"))
            conn.execute(text(f"ALTER INDEX IF EXISTS {temp_idx} RENAME TO {idx_name};"))
        return

    label = f"Building GIN FTS index on '{table_name}' (one-time migration)..." if has_rows else None
    _ensure_index(engine, conn, table_name, idx_name, "USING gin (fts)", has_rows=has_rows, migration_label=label)


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

        # Build/migrate indexes after the table/column transaction commits so CONCURRENTLY can run cleanly.
        if not is_sqlite:
            with engine.connect() as idx_conn, idx_conn.begin():
                _ensure_index(
                    engine, idx_conn, table_name,
                    f"idx_{table_name}_embedding", "USING hnsw (embedding vector_cosine_ops)",
                    has_rows=has_rows,
                    migration_label=f"Building HNSW embedding index on '{table_name}'...",
                )
                _migrate_fts_index(engine, idx_conn, table_name, has_rows=has_rows)
                _ensure_index(
                    engine, idx_conn, table_name,
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
                    _ensure_index(engine, idx_conn, table_name, f"idx_{table_name}_{suffix}", cols, has_rows=False)

        logger.info("PgVectorStore initialized table '%s' with %dd HNSW, GIN FTS, and file-lookup indexes.", table_name, dimension)
        return True
    except ValueError:
        raise
    except Exception as e:
        logger.error("Error initializing PgVectorStore table '%s': %s", table_name, e, exc_info=True)
        raise RuntimeError(f"Failed to initialize PgVectorStore table '{table_name}'.") from e
    finally:
        _set_migration_status(None)
