"""
PostgreSQL pgvector backend for vector storage and cosine similarity search.
Supports HNSW indexing, JSONB metadata payloads, and parameterized batch operations.
"""

import json
import logging
import os
import uuid
from typing import Any, Dict, List, Optional, Tuple, Union
from sqlalchemy import Engine, text

from app.services.database.engine import get_db_engine, is_postgres
from app.services.embeddings import get_dense_dim, get_dense_embedding
from app.services.text_decoding import strip_nul
from app.services.vector_store.base import VectorDocument, VectorSearchResult, VectorStore
from app.services.vector_store.pgvector_queries import (
    _FTS_STOPWORDS,
    _SEARCH_MODE_ALIASES,
    _build_or_tsquery,
    execute_pgvector_file_chunks,
    execute_pgvector_grep_chunks,
    execute_pgvector_search,
    parse_json_payload,
    sanitize_fts_query_text,
)

logger = logging.getLogger("contextcortex.vector_store.pgvector")

_MAX_LOGGED_ERROR_CHARS = 300


def _short_error(err: Exception) -> str:
    """First line of a database error, bounded: SQLAlchemy errors embed the full SQL and all parameters (chunk text)."""
    lines = str(getattr(err, "orig", None) or err).splitlines()
    first_line = lines[0] if lines else type(err).__name__
    return first_line[:_MAX_LOGGED_ERROR_CHARS]


class PgVectorStore(VectorStore):
    """VectorStore backend powered by PostgreSQL with the pgvector extension."""

    def __init__(
        self,
        database_url: Optional[str] = None,
        engine: Optional[Engine] = None,
        collection_name: Optional[str] = None,
        table_name: Optional[str] = "vector_documents",
        dimension: Optional[int] = None,
        auto_init: bool = True,
    ):
        self.collection_name = collection_name or os.getenv("COLLECTION_NAME", "knowledge_rag_v1")
        self.table_name = table_name or "vector_documents"
        self.engine = engine or get_db_engine(database_url)
        self.mode = "postgres"
        self.location = str(self.engine.url)

        try:
            self.dimension = dimension or get_dense_dim() or 384
        except Exception:
            self.dimension = dimension or 384

        if auto_init:
            self.ensure_collection()

    def ensure_collection(self) -> bool:
        """Initializes vector extension, documents table schema, and HNSW/GIN FTS indexes idempotently."""
        try:
            with self.engine.connect() as conn, conn.begin():
                is_sqlite = getattr(self.engine.dialect, "name", "") == "sqlite"

                if not is_sqlite:
                    extension = conn.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")).scalar()
                    if not extension:
                        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))

                    check_dim_sql = text("""
                        SELECT atttypmod FROM pg_attribute
                        WHERE attrelid = to_regclass(:table_name) AND attname = 'embedding';
                    """)
                    row = conn.execute(check_dim_sql, {"table_name": self.table_name}).fetchone()
                    if row and row[0] is not None and row[0] > 0 and row[0] != self.dimension:
                        conn.execute(text(f"LOCK TABLE {self.table_name} IN ACCESS EXCLUSIVE MODE"))
                        if conn.execute(text(f"SELECT EXISTS (SELECT 1 FROM {self.table_name})")).scalar():
                            raise ValueError(
                                f"Vector dimension mismatch for table '{self.table_name}': "
                                f"existing {row[0]}d, configured {self.dimension}d. "
                                "An explicit rebuild is required; all collections sharing this "
                                "table must be cleared before changing dimensions."
                            )
                        conn.execute(text(
                            f"ALTER TABLE {self.table_name} ALTER COLUMN embedding TYPE vector({self.dimension})"
                        ))

                create_table_sql = f"""
                CREATE TABLE IF NOT EXISTS {self.table_name} (
                    id VARCHAR(255),
                    collection_name VARCHAR(255) DEFAULT 'knowledge_rag_v1',
                    repo VARCHAR(255),
                    doc_type VARCHAR(50) DEFAULT 'doc',
                    path TEXT,
                    rel_path TEXT,
                    title TEXT,
                    folder TEXT,
                    category TEXT,
                    tags JSONB,
                    heading TEXT,
                    symbol TEXT,
                    language VARCHAR(50),
                    start_line INTEGER,
                    end_line INTEGER,
                    github_url TEXT,
                    permalink_url TEXT,
                    content TEXT,
                    embedding {"TEXT" if is_sqlite else "vector(" + str(self.dimension) + ")"},
                    payload JSONB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (collection_name, id)
                );
                """
                conn.execute(text(create_table_sql))

                if not is_sqlite:
                    conn.execute(text(
                        f"ALTER TABLE {self.table_name} ADD COLUMN IF NOT EXISTS collection_name VARCHAR(255) DEFAULT 'knowledge_rag_v1';"
                    ))
                    conn.execute(text(
                        f"UPDATE {self.table_name} SET collection_name = 'knowledge_rag_v1' WHERE collection_name IS NULL;"
                    ))

                    pk_check_sql = text("""
                        SELECT a.attname
                        FROM pg_index i
                        JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                        WHERE i.indrelid = CAST(:table_name AS regclass) AND i.indisprimary;
                    """)
                    pk_cols = [row[0] for row in conn.execute(pk_check_sql, {"table_name": self.table_name}).fetchall()]
                    if set(pk_cols) != {"collection_name", "id"}:
                        if pk_cols:
                            conname_sql = text("""
                                SELECT conname
                                FROM pg_constraint
                                WHERE conrelid = CAST(:table_name AS regclass) AND contype = 'p';
                            """)
                            conname_row = conn.execute(conname_sql, {"table_name": self.table_name}).fetchone()
                            if conname_row:
                                conname = self.engine.dialect.identifier_preparer.quote(conname_row[0])
                                conn.execute(text(f"ALTER TABLE {self.table_name} DROP CONSTRAINT {conname};"))
                        conn.execute(text(f"ALTER TABLE {self.table_name} ADD PRIMARY KEY (collection_name, id);"))

                    conn.execute(text(f"""
                    CREATE INDEX IF NOT EXISTS idx_{self.table_name}_embedding
                    ON {self.table_name} USING hnsw (embedding vector_cosine_ops);
                    """))
                    conn.execute(text(f"""
                    CREATE INDEX IF NOT EXISTS idx_{self.table_name}_fts
                    ON {self.table_name} USING gin (
                        to_tsvector(
                            'simple',
                            COALESCE(title, '') || ' ' || COALESCE(symbol, '') || ' ' || COALESCE(path, '') || ' ' || COALESCE(content, '')
                        )
                    );
                    """))
                    conn.execute(text(f"CREATE INDEX IF NOT EXISTS idx_{self.table_name}_collection ON {self.table_name}(collection_name);"))
                    conn.execute(text(f"CREATE INDEX IF NOT EXISTS idx_{self.table_name}_repo ON {self.table_name}(repo);"))
                    conn.execute(text(f"CREATE INDEX IF NOT EXISTS idx_{self.table_name}_type ON {self.table_name}(doc_type);"))
                    conn.execute(text(f"CREATE INDEX IF NOT EXISTS idx_{self.table_name}_path ON {self.table_name}(path);"))

            logger.info(f"PgVectorStore initialized table '{self.table_name}' with {self.dimension}d HNSW and GIN FTS indexes.")
            return True
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error initializing PgVectorStore table '{self.table_name}': {e}", exc_info=True)
            raise RuntimeError(f"Failed to initialize PgVectorStore table '{self.table_name}'.") from e

    def upsert_documents(
        self,
        documents: List[Union[VectorDocument, Dict[str, Any]]],
        batch_size: int = 100,
    ) -> bool:
        """Upserts a batch of document chunks with vector embeddings and JSON payloads."""
        if not documents:
            return True

        is_sqlite = getattr(self.engine.dialect, "name", "") == "sqlite"
        records = []
        for doc in documents:
            if isinstance(doc, VectorDocument):
                doc_id = str(doc.id)
                text_content = doc.text
                dense_vec = doc.dense_vector
                payload = doc.to_payload()
                tags, repo, doc_type = doc.tags, doc.repo, doc.doc_type
                path, rel_path, title, folder = doc.path, doc.rel_path, doc.title, doc.folder
                category, heading, symbol, language = doc.category, doc.heading, doc.symbol, doc.language
                start_line, end_line = doc.start_line, doc.end_line
                url = doc.permalink_url or doc.github_url
            else:
                doc_id = str(doc.get("id", uuid.uuid4()))
                text_content = doc.get("text", doc.get("content", ""))
                dense_vec = doc.get("dense_vector") or doc.get("dense")
                payload = doc.get("payload") if "payload" in doc else {
                    k: v for k, v in doc.items()
                    if k not in ("id", "text", "dense_vector", "sparse_indices", "sparse_values", "dense", "sparse")
                }
                tags, repo, doc_type = doc.get("tags", []), doc.get("repo"), doc.get("doc_type", "doc")
                path, rel_path, title, folder = doc.get("path"), doc.get("rel_path"), doc.get("title"), doc.get("folder")
                category, heading, symbol, language = doc.get("category"), doc.get("heading"), doc.get("symbol"), doc.get("language")
                start_line, end_line = doc.get("start_line"), doc.get("end_line")
                url = doc.get("permalink_url") or doc.get("github_url")

            if isinstance(text_content, str):
                text_content = text_content.replace("\x00", "")
            if isinstance(path, str):
                path = path.replace("\x00", "").replace("\\", "/")
            if isinstance(rel_path, str):
                rel_path = rel_path.replace("\x00", "").replace("\\", "/")
            if isinstance(folder, str):
                folder = folder.replace("\x00", "").replace("\\", "/")
            if isinstance(url, str):
                url = url.replace("\x00", "").replace("\\", "/")
            if isinstance(payload, dict):
                for pk in ("path", "rel_path", "filepath", "folder", "permalink_url", "github_url"):
                    if isinstance(payload.get(pk), str):
                        payload[pk] = payload[pk].replace("\x00", "").replace("\\", "/")

            if dense_vec is None and text_content:
                dense_vec = get_dense_embedding(text_content)

            if "content" not in payload and text_content:
                payload["content"] = text_content

            embedding_str = (json.dumps(dense_vec) if is_sqlite else str(dense_vec)) if dense_vec is not None else None
            # PostgreSQL rejects NUL in text and jsonb: sanitize the payload before json.dumps
            # (json.dumps writes NUL as \u0000) and every other string column.
            payload = strip_nul(payload)
            records.append(strip_nul({
                "id": doc_id,
                "collection_name": self.collection_name,
                "repo": repo,
                "doc_type": doc_type,
                "path": path,
                "rel_path": rel_path,
                "title": title,
                "folder": folder,
                "category": category,
                "tags": json.dumps(tags) if isinstance(tags, (list, dict)) else str(tags or "[]"),
                "heading": heading,
                "symbol": symbol,
                "language": language,
                "start_line": start_line,
                "end_line": end_line,
                "github_url": url,
                "permalink_url": url,
                "content": text_content,
                "embedding": embedding_str,
                "payload": json.dumps(payload),
            }))

        upsert_sql = text(f"""
        INSERT INTO {self.table_name} (
            id, collection_name, repo, doc_type, path, rel_path, title, folder,
            category, tags, heading, symbol, language, start_line,
            end_line, github_url, permalink_url, content, embedding, payload
        ) VALUES (
            :id, :collection_name, :repo, :doc_type, :path, :rel_path, :title, :folder,
            :category, :tags, :heading, :symbol, :language, :start_line,
            :end_line, :github_url, :permalink_url, :content, :embedding, :payload
        )
        ON CONFLICT (collection_name, id) DO UPDATE SET
            repo = EXCLUDED.repo, doc_type = EXCLUDED.doc_type, path = EXCLUDED.path,
            rel_path = EXCLUDED.rel_path, title = EXCLUDED.title, folder = EXCLUDED.folder,
            category = EXCLUDED.category, tags = EXCLUDED.tags, heading = EXCLUDED.heading,
            symbol = EXCLUDED.symbol, language = EXCLUDED.language, start_line = EXCLUDED.start_line,
            end_line = EXCLUDED.end_line, github_url = EXCLUDED.github_url,
            permalink_url = EXCLUDED.permalink_url, content = EXCLUDED.content,
            embedding = EXCLUDED.embedding, payload = EXCLUDED.payload;
        """)

        effective_batch_size = max(1, batch_size)
        failed_ids: List[str] = []
        try:
            with self.engine.connect() as conn:
                for i in range(0, len(records), effective_batch_size):
                    batch = records[i : i + effective_batch_size]
                    try:
                        conn.execute(upsert_sql, batch)
                        conn.commit()
                    except Exception as batch_err:
                        # One bad record must not fail the batch, the file set, or the repository:
                        # retry the records one by one and skip only the ones that fail.
                        conn.rollback()
                        logger.warning(
                            f"Batch upsert into '{self.table_name}' failed ({_short_error(batch_err)}); "
                            f"retrying {len(batch)} records one by one."
                        )
                        failed_ids.extend(self._upsert_records_individually(conn, upsert_sql, batch))
        except Exception as e:
            logger.error(f"Error upserting documents into PgVectorStore table '{self.table_name}': {e}", exc_info=True)
            return False

        if failed_ids:
            logger.error(
                f"Skipped {len(failed_ids)} of {len(records)} documents that PgVectorStore table '{self.table_name}' "
                f"rejected (first ids: {[str(i)[:80] for i in failed_ids[:5]]})."
            )
        return len(failed_ids) < len(records)

    def _upsert_records_individually(self, conn, upsert_sql, batch: List[Dict[str, Any]]) -> List[str]:
        """Upserts records one at a time after a failed batch; returns the ids of the records that still fail."""
        failed: List[str] = []
        for record in batch:
            try:
                conn.execute(upsert_sql, record)
                conn.commit()
            except Exception as record_err:
                conn.rollback()
                failed.append(record["id"])
                logger.warning(
                    f"PgVectorStore rejected document {str(record['id'])[:80]} ({record.get('path')}): {_short_error(record_err)}"
                )
        return failed

    def delete_by_path(self, filepath: str) -> bool:
        """Purges vectors associated with a specific file path."""
        norm_fp = (filepath or "").replace("\\", "/")
        try:
            with self.engine.connect() as conn:
                conn.execute(
                    text(f"DELETE FROM {self.table_name} WHERE collection_name = :collection_name AND (path = :path OR path = :norm_path)"),
                    {"collection_name": self.collection_name, "path": filepath, "norm_path": norm_fp},
                )
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error deleting by path '{filepath}' in PgVectorStore: {e}")
            return False

    def delete_by_repo(self, repo_name: str) -> bool:
        """Purges all vectors belonging to a repository."""
        try:
            with self.engine.connect() as conn:
                conn.execute(
                    text(f"DELETE FROM {self.table_name} WHERE collection_name = :collection_name AND repo = :repo"),
                    {"collection_name": self.collection_name, "repo": repo_name},
                )
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error deleting by repo '{repo_name}' in PgVectorStore: {e}")
            return False

    def delete_collection(self, collection_name: Optional[str] = None) -> bool:
        """Purges all vectors belonging to a specific collection (defaults to active collection)."""
        target_coll = collection_name or self.collection_name
        try:
            with self.engine.connect() as conn:
                conn.execute(
                    text(f"DELETE FROM {self.table_name} WHERE collection_name = :collection_name"),
                    {"collection_name": target_coll},
                )
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error deleting collection '{target_coll}' in PgVectorStore: {e}")
            return False

    def clear_collection(self, collection_name: Optional[str] = None) -> bool:
        return self.delete_collection(collection_name)

    def search(
        self,
        query_text: str,
        doc_type: Optional[str] = None,
        repo: Optional[str] = None,
        language: Optional[str] = None,
        category: Optional[str] = None,
        tag: Optional[str] = None,
        limit: int = 5,
        dense_weight: Optional[float] = None,
        search_mode: str = "semantic",
    ) -> List[VectorSearchResult]:
        supported = self.get_capabilities().get("search_modes", ["hybrid", "semantic", "lexical"])
        return execute_pgvector_search(
            engine=self.engine,
            table_name=self.table_name,
            collection_name=self.collection_name,
            dimension=self.dimension,
            supported_modes=supported,
            embed_fn=get_dense_embedding,
            query_text=query_text,
            doc_type=doc_type,
            repo=repo,
            language=language,
            category=category,
            tag=tag,
            limit=limit,
            dense_weight=dense_weight,
            search_mode=search_mode,
        )

    @staticmethod
    def _parse_payload(raw_payload: Any) -> Dict[str, Any]:
        return parse_json_payload(raw_payload)

    def get_capabilities(self) -> Dict[str, Any]:
        return {"search_modes": ["hybrid", "semantic", "lexical"], "supports_weighting": True}

    def get_stats(self) -> Dict[str, Any]:
        try:
            with self.engine.connect() as conn:
                count = conn.execute(
                    text(f"SELECT count(*) FROM {self.table_name} WHERE collection_name = :collection_name"),
                    {"collection_name": self.collection_name},
                ).scalar() or 0
            return {
                "backend": "pgvector",
                "mode": self.mode,
                "collection_name": self.collection_name,
                "table_name": self.table_name,
                "exists": True,
                "points_count": int(count),
                "vectors_count": int(count),
                "location": self.location,
                "capabilities": self.get_capabilities(),
            }
        except Exception as e:
            logger.error(f"Error getting stats from PgVectorStore: {e}")
            return {
                "backend": "pgvector",
                "mode": self.mode,
                "collection_name": self.collection_name,
                "table_name": self.table_name,
                "exists": False,
                "error": "Failed to retrieve PgVectorStore statistics.",
                "location": self.location,
                "capabilities": self.get_capabilities(),
            }

    def health_check(self) -> Tuple[bool, str]:
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1;"))
                conn.execute(text(f"SELECT 1 FROM {self.table_name} LIMIT 1;"))
            return True, f"PgVectorStore ({self.location}) is healthy; table '{self.table_name}' verified"
        except Exception as e:
            logger.warning(f"PgVectorStore health check failed: {e}")
            return False, "PgVectorStore health check failed."

    def get_file_chunks(self, path: str, repo: Optional[str] = None) -> List[Dict[str, Any]]:
        return execute_pgvector_file_chunks(
            engine=self.engine, table_name=self.table_name,
            collection_name=self.collection_name, path=path, repo=repo,
        )

    def grep_chunks(
        self,
        pattern: str,
        repo: Optional[str] = None,
        path_glob: Optional[str] = None,
        is_regex: bool = False,
        case_sensitive: bool = False,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        return execute_pgvector_grep_chunks(
            engine=self.engine, table_name=self.table_name, collection_name=self.collection_name,
            pattern=pattern, repo=repo, path_glob=path_glob,
            is_regex=is_regex, case_sensitive=case_sensitive, limit=limit,
        )

    def close(self) -> None:
        pass


__all__ = [
    "PgVectorStore",
    "_build_or_tsquery",
    "_SEARCH_MODE_ALIASES",
    "_FTS_STOPWORDS",
    "sanitize_fts_query_text",
]
