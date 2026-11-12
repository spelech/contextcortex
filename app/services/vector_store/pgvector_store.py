"""
PostgreSQL pgvector backend for vector storage and cosine similarity search.
Supports HNSW indexing, JSONB metadata payloads, and parameterized batch operations.
"""

import os
import re
import json
import uuid
import logging
from typing import List, Dict, Any, Optional, Tuple, Union
from sqlalchemy import Engine, text

from app.services.vector_store.base import VectorStore, VectorDocument, VectorSearchResult
from app.services.database.engine import get_db_engine, is_postgres
from app.services.embeddings import get_dense_embedding, get_dense_dim

logger = logging.getLogger("contextcortex.vector_store.pgvector")

_SEARCH_MODE_ALIASES = {
    "keyword": "lexical",
    "keywords": "lexical",
    "bm25": "lexical",
    "fulltext": "lexical",
    "fts": "lexical",
    "vector": "semantic",
    "dense": "semantic",
    "sparse": "lexical",
}

_FTS_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "can", "could",
    "did", "do", "does", "for", "from", "had", "has", "have", "how", "if",
    "in", "into", "is", "it", "its", "may", "might", "not", "of", "on", "or",
    "our", "should", "so", "such", "than", "that", "the", "their", "them",
    "then", "there", "these", "they", "this", "to", "too", "up", "use", "used",
    "using", "was", "we", "were", "what", "when", "where", "which", "who",
    "why", "will", "with", "would", "you", "your",
})


def _build_or_tsquery(query_text: str) -> str:
    """
    Builds a safe PostgreSQL tsquery string joining significant query tokens with '|' (OR).
    Allows natural-language questions (e.g. 'how does the worker decide that a record needs action')
    to score documents matching a subset of terms under the 'simple' FTS dictionary.
    """
    raw_tokens = re.findall(r"[A-Za-z0-9_]{2,}", (query_text or "").lower())
    if not raw_tokens:
        return ""
    filtered = [t for t in raw_tokens if t not in _FTS_STOPWORDS]
    tokens = filtered if filtered else raw_tokens
    seen = []
    for t in tokens:
        if t not in seen:
            seen.append(t)
        if len(seen) >= 16:
            break
    return " | ".join(seen)


class PgVectorStore(VectorStore):
    """
    VectorStore backend powered by PostgreSQL with the pgvector extension.
    Uses HNSW indexing and cosine similarity (<=>) for high-performance retrieval.
    """

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
        """
        Initializes vector extension, documents table schema, and HNSW indexes idempotently.

        Schema changes are atomic. Populated tables require an explicit rebuild before
        changing dimensions, because all collections share the embedding column.
        """
        try:
            with self.engine.connect() as conn, conn.begin():
                is_sqlite = getattr(self.engine.dialect, "name", "") == "sqlite"

                if not is_sqlite:
                    # An installed extension needs no CREATE privilege.
                    extension = conn.execute(text(
                        "SELECT 1 FROM pg_extension WHERE extname = 'vector'"
                    )).scalar()
                    if not extension:
                        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))

                    # to_regclass returns NULL for a fresh table instead of aborting the transaction.
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

                # 2. Create vector documents table
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
                    # Migrate legacy rows before replacing the old id-only primary key.
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

                    # 3. Create HNSW cosine index
                    hnsw_index_sql = f"""
                    CREATE INDEX IF NOT EXISTS idx_{self.table_name}_embedding
                    ON {self.table_name} USING hnsw (embedding vector_cosine_ops);
                    """
                    conn.execute(text(hnsw_index_sql))

                    # 4. Create GIN Full-Text Search index for native lexical & hybrid search
                    fts_index_sql = f"""
                    CREATE INDEX IF NOT EXISTS idx_{self.table_name}_fts
                    ON {self.table_name} USING gin (
                        to_tsvector(
                            'simple',
                            COALESCE(title, '') || ' ' || COALESCE(symbol, '') || ' ' || COALESCE(path, '') || ' ' || COALESCE(content, '')
                        )
                    );
                    """
                    conn.execute(text(fts_index_sql))

                    # 5. Create metadata indexes
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
        """
        Upserts a batch of document chunks with vector embeddings and JSON payloads.
        """
        if not documents:
            return True

        records = []
        for doc in documents:
            if isinstance(doc, VectorDocument):
                doc_id = str(doc.id)
                text_content = doc.text
                dense_vec = doc.dense_vector
                payload = doc.to_payload()
                tags = doc.tags
                repo = doc.repo
                doc_type = doc.doc_type
                path = doc.path
                rel_path = doc.rel_path
                title = doc.title
                folder = doc.folder
                category = doc.category
                heading = doc.heading
                symbol = doc.symbol
                language = doc.language
                start_line = doc.start_line
                end_line = doc.end_line
                url = doc.permalink_url or doc.github_url
            else:
                doc_id = str(doc.get("id", uuid.uuid4()))
                text_content = doc.get("text", doc.get("content", ""))
                dense_vec = doc.get("dense_vector") or doc.get("dense")
                payload = doc.get("payload") if "payload" in doc else {
                    k: v for k, v in doc.items()
                    if k not in ("id", "text", "dense_vector", "sparse_indices", "sparse_values", "dense", "sparse")
                }
                tags = doc.get("tags", [])
                repo = doc.get("repo")
                doc_type = doc.get("doc_type", "doc")
                path = doc.get("path")
                rel_path = doc.get("rel_path")
                title = doc.get("title")
                folder = doc.get("folder")
                category = doc.get("category")
                heading = doc.get("heading")
                symbol = doc.get("symbol")
                language = doc.get("language")
                start_line = doc.get("start_line")
                end_line = doc.get("end_line")
                url = doc.get("permalink_url") or doc.get("github_url")

            if isinstance(path, str):
                path = path.replace("\\", "/")
            if isinstance(rel_path, str):
                rel_path = rel_path.replace("\\", "/")
            if isinstance(folder, str):
                folder = folder.replace("\\", "/")
            if isinstance(url, str):
                url = url.replace("\\", "/")
            if isinstance(payload, dict):
                for pk in ("path", "rel_path", "filepath", "folder", "permalink_url", "github_url"):
                    if isinstance(payload.get(pk), str):
                        payload[pk] = payload[pk].replace("\\", "/")

            if dense_vec is None and text_content:
                dense_vec = get_dense_embedding(text_content)

            if "content" not in payload and text_content:
                payload["content"] = text_content

            embedding_str = str(dense_vec) if dense_vec is not None else None

            records.append({
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
            })

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
            repo = EXCLUDED.repo,
            doc_type = EXCLUDED.doc_type,
            path = EXCLUDED.path,
            rel_path = EXCLUDED.rel_path,
            title = EXCLUDED.title,
            folder = EXCLUDED.folder,
            category = EXCLUDED.category,
            tags = EXCLUDED.tags,
            heading = EXCLUDED.heading,
            symbol = EXCLUDED.symbol,
            language = EXCLUDED.language,
            start_line = EXCLUDED.start_line,
            end_line = EXCLUDED.end_line,
            github_url = EXCLUDED.github_url,
            permalink_url = EXCLUDED.permalink_url,
            content = EXCLUDED.content,
            embedding = EXCLUDED.embedding,
            payload = EXCLUDED.payload;
        """)

        effective_batch_size = max(1, batch_size)
        try:
            with self.engine.connect() as conn:
                for i in range(0, len(records), effective_batch_size):
                    chunk = records[i : i + effective_batch_size]
                    conn.execute(upsert_sql, chunk)
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error upserting documents into PgVectorStore table '{self.table_name}': {e}", exc_info=True)
            return False

    def delete_by_path(self, filepath: str) -> bool:
        """Purges vectors associated with a specific file path."""
        try:
            with self.engine.connect() as conn:
                conn.execute(
                    text(f"DELETE FROM {self.table_name} WHERE collection_name = :collection_name AND path = :path"),
                    {"collection_name": self.collection_name, "path": filepath},
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
        """Alias for delete_collection."""
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
        """
        Performs semantic (cosine distance), lexical (PostgreSQL tsvector/ts_rank_cd),
        or weighted hybrid search returning ranked results without ONNX/FastEmbed.
        """
        if not query_text or not query_text.strip():
            return []

        raw_mode = (search_mode or "semantic").lower().strip()
        mode = _SEARCH_MODE_ALIASES.get(raw_mode, raw_mode)
        caps = self.get_capabilities()
        supported = caps.get("search_modes", ["hybrid", "semantic", "lexical"])
        if mode not in supported:
            raise ValueError(
                f"Search mode '{search_mode}' is not supported by PgVector vector store. "
                f"Supported modes: {supported}"
            )

        if mode == "semantic":
            alpha = 1.0
        elif mode == "lexical":
            alpha = 0.0
        elif dense_weight is not None:
            try:
                alpha = float(dense_weight)
            except (ValueError, TypeError):
                alpha = 0.5
            alpha = max(0.0, min(1.0, alpha))
        else:
            try:
                env_alpha = os.getenv("HYBRID_DENSE_WEIGHT")
                alpha = float(env_alpha) if env_alpha is not None else 0.5
            except (ValueError, TypeError):
                alpha = 0.5
            alpha = max(0.0, min(1.0, alpha))

        try:
            conditions = ["collection_name = :collection_name"]
            params: Dict[str, Any] = {
                "collection_name": self.collection_name,
                "limit": limit,
            }

            if doc_type:
                if doc_type == "doc":
                    conditions.append("doc_type IN ('doc', 'pdf')")
                else:
                    conditions.append("doc_type = :doc_type")
                    params["doc_type"] = doc_type
            if repo:
                conditions.append("repo = :repo")
                params["repo"] = repo
            if language:
                conditions.append("language = :language")
                params["language"] = language
            if category:
                conditions.append("category = :category")
                params["category"] = category
            if tag:
                conditions.append("(tags @> CAST(:tag_json AS jsonb) OR tags::text LIKE :tag_like)")
                params["tag_json"] = json.dumps([tag])
                params["tag_like"] = f'%"{tag}"%'

            where_clause = " AND ".join(conditions)
            fts_expr = (
                "to_tsvector('simple', COALESCE(title, '') || ' ' || COALESCE(symbol, '') || ' ' || COALESCE(path, '') || ' ' || COALESCE(content, ''))"
            )
            or_tsq = _build_or_tsquery(query_text)
            if or_tsq:
                params["tsq_or"] = or_tsq
                tsq_expr = "(websearch_to_tsquery('simple', :query_text) || to_tsquery('simple', :tsq_or))"
            else:
                tsq_expr = "websearch_to_tsquery('simple', :query_text)"

            # 1. Pure Semantic Search
            if mode == "semantic" or (mode == "hybrid" and alpha >= 1.0):
                query_vec = get_dense_embedding(query_text.strip())
                if len(query_vec) != self.dimension:
                    msg = f"Vector dimension mismatch: query vector ({len(query_vec)}d) does not match PgVectorStore table '{self.table_name}' ({self.dimension}d). An index rebuild is required."
                    logger.error(msg)
                    raise ValueError(msg)

                params["query_vec"] = str(query_vec)
                search_sql = text(f"""
                SELECT id, (1 - (embedding <=> CAST(:query_vec AS vector))) AS score, payload
                FROM {self.table_name}
                WHERE {where_clause}
                ORDER BY embedding <=> CAST(:query_vec AS vector)
                LIMIT :limit;
                """)

                with self.engine.connect() as conn:
                    rows = conn.execute(search_sql, params).mappings().fetchall()

                results: List[VectorSearchResult] = []
                for rank_idx, row in enumerate(rows, start=1):
                    payload = self._parse_payload(row["payload"])
                    score = float(row["score"]) if row["score"] is not None else 0.0
                    clamped_score = max(0.0, min(1.0, score))
                    results.append(
                        VectorSearchResult(
                            id=str(row["id"]),
                            score=round(clamped_score, 4),
                            dense_score=round(clamped_score, 4),
                            sparse_score=0.0,
                            dense_rank=rank_idx,
                            sparse_rank=None,
                            payload=payload,
                        )
                    )
                return results

            # 2. Pure Lexical Search (PostgreSQL Full-Text Search)
            if mode == "lexical" or (mode == "hybrid" and alpha <= 0.0):
                params["query_text"] = query_text.strip()
                lexical_sql = text(f"""
                SELECT id, ts_rank_cd({fts_expr}, {tsq_expr}) AS sparse_score, payload
                FROM {self.table_name}
                WHERE {where_clause} AND {fts_expr} @@ {tsq_expr}
                ORDER BY sparse_score DESC
                LIMIT :limit;
                """)
                with self.engine.connect() as conn:
                    rows = conn.execute(lexical_sql, params).mappings().fetchall()

                max_sparse = max((float(r["sparse_score"] or 0.0) for r in rows), default=1.0)
                if max_sparse <= 0.0:
                    max_sparse = 1.0

                results = []
                for rank_idx, row in enumerate(rows, start=1):
                    payload = self._parse_payload(row["payload"])
                    raw_s = float(row["sparse_score"] or 0.0)
                    norm_s = max(0.0, min(1.0, raw_s / max_sparse))
                    results.append(
                        VectorSearchResult(
                            id=str(row["id"]),
                            score=round(norm_s, 4),
                            dense_score=0.0,
                            sparse_score=round(norm_s, 4),
                            dense_rank=None,
                            sparse_rank=rank_idx,
                            payload=payload,
                        )
                    )
                return results

            # 3. Hybrid Search (Dense Cosine + Native PostgreSQL FTS Fusion)
            query_vec = get_dense_embedding(query_text.strip())
            if len(query_vec) != self.dimension:
                msg = f"Vector dimension mismatch: query vector ({len(query_vec)}d) does not match PgVectorStore table '{self.table_name}' ({self.dimension}d). An index rebuild is required."
                logger.error(msg)
                raise ValueError(msg)

            candidate_limit = max(limit * 5, 50)
            params["query_vec"] = str(query_vec)
            params["query_text"] = query_text.strip()
            params["candidate_limit"] = candidate_limit

            dense_sql = text(f"""
            SELECT id, (1 - (embedding <=> CAST(:query_vec AS vector))) AS score, payload
            FROM {self.table_name}
            WHERE {where_clause}
            ORDER BY embedding <=> CAST(:query_vec AS vector)
            LIMIT :candidate_limit;
            """)
            lexical_sql = text(f"""
            SELECT id, ts_rank_cd({fts_expr}, {tsq_expr}) AS sparse_score, payload
            FROM {self.table_name}
            WHERE {where_clause} AND {fts_expr} @@ {tsq_expr}
            ORDER BY sparse_score DESC
            LIMIT :candidate_limit;
            """)

            with self.engine.connect() as conn:
                dense_rows = conn.execute(dense_sql, params).mappings().fetchall()
                lexical_rows = conn.execute(lexical_sql, params).mappings().fetchall()

            merged: Dict[str, Dict[str, Any]] = {}
            for d_rank, row in enumerate(dense_rows, start=1):
                doc_id = str(row["id"])
                d_score = max(0.0, min(1.0, float(row["score"] or 0.0)))
                merged[doc_id] = {
                    "id": doc_id,
                    "dense_score": d_score,
                    "sparse_score": 0.0,
                    "dense_rank": d_rank,
                    "sparse_rank": None,
                    "payload": self._parse_payload(row["payload"]),
                }

            max_sparse = max((float(r["sparse_score"] or 0.0) for r in lexical_rows), default=1.0)
            if max_sparse <= 0.0:
                max_sparse = 1.0

            for s_rank, row in enumerate(lexical_rows, start=1):
                doc_id = str(row["id"])
                norm_s = max(0.0, min(1.0, float(row["sparse_score"] or 0.0) / max_sparse))
                if doc_id in merged:
                    merged[doc_id]["sparse_score"] = norm_s
                    merged[doc_id]["sparse_rank"] = s_rank
                else:
                    merged[doc_id] = {
                        "id": doc_id,
                        "dense_score": 0.0,
                        "sparse_score": norm_s,
                        "dense_rank": None,
                        "sparse_rank": s_rank,
                        "payload": self._parse_payload(row["payload"]),
                    }

            fused: List[VectorSearchResult] = []
            for item in merged.values():
                combined = (alpha * item["dense_score"]) + ((1.0 - alpha) * item["sparse_score"])
                fused.append(
                    VectorSearchResult(
                        id=item["id"],
                        score=round(combined, 4),
                        dense_score=round(item["dense_score"], 4),
                        sparse_score=round(item["sparse_score"], 4),
                        dense_rank=item["dense_rank"],
                        sparse_rank=item["sparse_rank"],
                        payload=item["payload"],
                    )
                )

            fused.sort(key=lambda r: r.score, reverse=True)
            return fused[:limit]
        except ValueError:
            raise
        except Exception as e:
            err_str = str(e).lower()
            if "dimension" in err_str or "different size" in err_str or "mismatch" in err_str:
                msg = f"Vector dimension mismatch during PgVector search in table '{self.table_name}': {e}. An index rebuild is required."
                logger.error(msg)
                raise ValueError(msg) from e
            logger.error(f"Error searching PgVectorStore table '{self.table_name}': {e}", exc_info=True)
            return []

    @staticmethod
    def _parse_payload(raw_payload: Any) -> Dict[str, Any]:
        if isinstance(raw_payload, str):
            try:
                return json.loads(raw_payload)
            except Exception:
                return {}
        elif isinstance(raw_payload, dict):
            return raw_payload
        return {}

    def get_capabilities(self) -> Dict[str, Any]:
        """Returns capabilities supported by PgVector vector store backend."""
        return {
            "search_modes": ["hybrid", "semantic", "lexical"],
            "supports_weighting": True,
        }

    def get_stats(self) -> Dict[str, Any]:
        """Returns table statistics including row count and backend mode."""
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
                "error": str(e),
                "location": self.location,
                "capabilities": self.get_capabilities(),
            }

    def health_check(self) -> Tuple[bool, str]:
        """Validates connection and presence of the vector documents table."""
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1;"))
                conn.execute(text(f"SELECT 1 FROM {self.table_name} LIMIT 1;"))
            return True, f"PgVectorStore ({self.location}) is healthy; table '{self.table_name}' verified"
        except Exception as e:
            logger.warning(f"PgVectorStore health check failed: {e}")
            return False, "PgVectorStore health check failed."

    def get_file_chunks(self, path: str, repo: Optional[str] = None) -> List[Dict[str, Any]]:
        """Returns all chunk payloads for the specified path / rel_path (and optional repo), sorted by (start_line, end_line)."""
        clean_path = path.replace("\\", "/").strip("/")
        rel_path = clean_path.split("://", 1)[1] if "://" in clean_path else clean_path
        if repo and rel_path.startswith(f"{repo}/"):
            rel_path = rel_path[len(repo) + 1:]

        conditions = [
            "collection_name = :collection_name",
            "(rel_path = :rel_path OR path = :path OR rel_path = :path OR path = :rel_path OR path LIKE :path_suffix)"
        ]
        params: Dict[str, Any] = {
            "collection_name": self.collection_name,
            "rel_path": rel_path,
            "path": path,
            "path_suffix": f"%://{repo}/{rel_path}" if (repo and repo not in ("__all__", "all")) else f"%/{rel_path}",
        }
        if repo and repo not in ("__all__", "all"):
            conditions.append("repo = :repo")
            params["repo"] = repo

        where_clause = " AND ".join(conditions)
        query_sql = text(f"""
        SELECT payload, content, start_line, end_line, repo, path, rel_path
        FROM {self.table_name}
        WHERE {where_clause}
        ORDER BY COALESCE(start_line, 0) ASC, COALESCE(end_line, 0) ASC;
        """)

        try:
            with self.engine.connect() as conn:
                rows = conn.execute(query_sql, params).mappings().fetchall()

            chunks: List[Dict[str, Any]] = []
            for r in rows:
                p = self._parse_payload(r["payload"])
                if "content" not in p and r["content"]:
                    p["content"] = r["content"]
                if "start_line" not in p and r["start_line"] is not None:
                    p["start_line"] = r["start_line"]
                if "end_line" not in p and r["end_line"] is not None:
                    p["end_line"] = r["end_line"]
                if "repo" not in p and r["repo"]:
                    p["repo"] = r["repo"]
                if "path" not in p and r["path"]:
                    p["path"] = r["path"]
                if "rel_path" not in p and r["rel_path"]:
                    p["rel_path"] = r["rel_path"]
                chunks.append(p)

            chunks.sort(key=lambda p: (p.get("start_line") or 0, p.get("end_line") or 0))
            return chunks
        except Exception as e:
            logger.error(f"Error fetching file chunks from PgVectorStore: {e}")
            return []

    def grep_chunks(
        self,
        pattern: str,
        repo: Optional[str] = None,
        path_glob: Optional[str] = None,
        is_regex: bool = False,
        case_sensitive: bool = False,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Queries chunks matching pattern using parameterized SQL over table_name."""
        import fnmatch
        import re

        is_sqlite = getattr(self.engine.dialect, "name", "") == "sqlite"

        # Validate regex syntax if requested
        if is_regex:
            re.compile(pattern)

        conditions = ["collection_name = :collection_name"]
        params: Dict[str, Any] = {
            "collection_name": self.collection_name,
            "limit": limit,
        }

        if repo and repo not in ("__all__", "all"):
            conditions.append("repo = :repo")
            params["repo"] = repo

        # Filtering pattern in SQL
        if not is_sqlite:
            # PostgreSQL
            if is_regex:
                op = "~" if case_sensitive else "~*"
                conditions.append(f"content {op} :pattern")
                params["pattern"] = pattern
            else:
                op = "LIKE" if case_sensitive else "ILIKE"
                # Escape % and _ in pattern for LIKE
                escaped = pattern.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                conditions.append(f"content {op} :pattern")
                params["pattern"] = f"%{escaped}%"
        else:
            # SQLite: LIKE is case-insensitive for ASCII, but we'll filter in Python if needed
            if not is_regex:
                escaped = pattern.replace("/", "//").replace("%", "/%").replace("_", "/_")
                conditions.append("content LIKE :pattern ESCAPE '/'")
                params["pattern"] = f"%{escaped}%"

        where_clause = " AND ".join(conditions)
        query_sql = text(f"""
        SELECT payload, content, start_line, end_line, repo, path, rel_path
        FROM {self.table_name}
        WHERE {where_clause}
        LIMIT :limit;
        """)

        try:
            with self.engine.connect() as conn:
                rows = conn.execute(query_sql, params).mappings().fetchall()

            flags = 0 if case_sensitive else re.IGNORECASE
            regex_pat = pattern if is_regex else re.escape(pattern)
            compiled = re.compile(regex_pat, flags)

            matched_chunks: List[Dict[str, Any]] = []
            for r in rows:
                p = self._parse_payload(r["payload"])
                if "content" not in p and r["content"]:
                    p["content"] = r["content"]
                if "start_line" not in p and r["start_line"] is not None:
                    p["start_line"] = r["start_line"]
                if "end_line" not in p and r["end_line"] is not None:
                    p["end_line"] = r["end_line"]
                if "repo" not in p and r["repo"]:
                    p["repo"] = r["repo"]
                if "path" not in p and r["path"]:
                    p["path"] = r["path"]
                if "rel_path" not in p and r["rel_path"]:
                    p["rel_path"] = r["rel_path"]

                chunk_path = p.get("rel_path") or p.get("path") or ""
                if path_glob:
                    norm_p = chunk_path.replace("\\", "/")
                    norm_glob = path_glob.replace("\\", "/")
                    if not (fnmatch.fnmatch(norm_p, norm_glob) or fnmatch.fnmatch(os.path.basename(norm_p), norm_glob)):
                        continue

                content = p.get("content") or ""
                if compiled.search(content):
                    matched_chunks.append(p)
                    if len(matched_chunks) >= limit:
                        break

            return matched_chunks[:limit]
        except Exception as e:
            logger.error(f"Error running grep_chunks on PgVectorStore: {e}")
            raise

    def close(self):
        """Disposes underlying database handles if necessary."""
        pass
