"""
PostgreSQL pgvector backend for vector storage and cosine similarity search.
Supports HNSW indexing, JSONB metadata payloads, and parameterized batch operations.
"""

import os
import json
import uuid
import logging
from typing import List, Dict, Any, Optional, Tuple, Union
from sqlalchemy import Engine, text

from app.services.vector_store.base import VectorStore, VectorDocument, VectorSearchResult
from app.services.database.engine import get_db_engine, is_postgres
from app.services.embeddings import get_dense_embedding, get_dense_dim

logger = logging.getLogger("contextcortex.vector_store.pgvector")


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
        """
        try:
            with self.engine.connect() as conn:
                # 1. Enable pgvector extension
                try:
                    conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
                    conn.commit()
                except Exception as ext_err:
                    logger.warning(
                        f"Could not automatically create 'vector' extension (may require superuser or already exist): {ext_err}"
                    )

                # 2. Create vector documents table
                create_table_sql = f"""
                CREATE TABLE IF NOT EXISTS {self.table_name} (
                    id VARCHAR(255) PRIMARY KEY,
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
                    embedding vector({self.dimension}),
                    payload JSONB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
                conn.execute(text(create_table_sql))

                # 3. Create HNSW cosine index
                hnsw_index_sql = f"""
                CREATE INDEX IF NOT EXISTS idx_{self.table_name}_embedding
                ON {self.table_name} USING hnsw (embedding vector_cosine_ops);
                """
                conn.execute(text(hnsw_index_sql))

                # 4. Create metadata indexes
                conn.execute(text(f"CREATE INDEX IF NOT EXISTS idx_{self.table_name}_repo ON {self.table_name}(repo);"))
                conn.execute(text(f"CREATE INDEX IF NOT EXISTS idx_{self.table_name}_type ON {self.table_name}(doc_type);"))
                conn.execute(text(f"CREATE INDEX IF NOT EXISTS idx_{self.table_name}_path ON {self.table_name}(path);"))

                conn.commit()
            logger.info(f"PgVectorStore initialized table '{self.table_name}' with {self.dimension}d HNSW index.")
            return True
        except Exception as e:
            logger.error(f"Error initializing PgVectorStore table '{self.table_name}': {e}", exc_info=True)
            return False

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

            if dense_vec is None and text_content:
                dense_vec = get_dense_embedding(text_content)

            if "content" not in payload and text_content:
                payload["content"] = text_content

            embedding_str = str(dense_vec) if dense_vec is not None else None

            records.append({
                "id": doc_id,
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
            id, repo, doc_type, path, rel_path, title, folder,
            category, tags, heading, symbol, language, start_line,
            end_line, github_url, permalink_url, content, embedding, payload
        ) VALUES (
            :id, :repo, :doc_type, :path, :rel_path, :title, :folder,
            :category, :tags, :heading, :symbol, :language, :start_line,
            :end_line, :github_url, :permalink_url, :content, :embedding, :payload
        )
        ON CONFLICT (id) DO UPDATE SET
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
                    text(f"DELETE FROM {self.table_name} WHERE path = :path"),
                    {"path": filepath},
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
                    text(f"DELETE FROM {self.table_name} WHERE repo = :repo"),
                    {"repo": repo_name},
                )
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error deleting by repo '{repo_name}' in PgVectorStore: {e}")
            return False

    def search(
        self,
        query_text: str,
        doc_type: Optional[str] = None,
        repo: Optional[str] = None,
        language: Optional[str] = None,
        category: Optional[str] = None,
        tag: Optional[str] = None,
        limit: int = 5,
    ) -> List[VectorSearchResult]:
        """
        Performs cosine distance vector search returning ranked results.
        """
        if not query_text or not query_text.strip():
            return []

        try:
            query_vec = get_dense_embedding(query_text.strip())
            query_vec_str = str(query_vec)

            conditions = ["1=1"]
            params: Dict[str, Any] = {
                "query_vec": query_vec_str,
                "limit": limit,
            }

            if doc_type:
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
                conditions.append("(tags @> :tag_json OR tags::text LIKE :tag_like)")
                params["tag_json"] = json.dumps([tag])
                params["tag_like"] = f'%"{tag}"%'

            where_clause = " AND ".join(conditions)
            search_sql = text(f"""
            SELECT id, (1 - (embedding <=> :query_vec)) AS score, payload
            FROM {self.table_name}
            WHERE {where_clause}
            ORDER BY embedding <=> :query_vec
            LIMIT :limit;
            """)

            with self.engine.connect() as conn:
                rows = conn.execute(search_sql, params).mappings().fetchall()

            results: List[VectorSearchResult] = []
            for row in rows:
                payload = row["payload"]
                if isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                    except Exception:
                        payload = {}
                elif not isinstance(payload, dict):
                    payload = {}

                score = float(row["score"]) if row["score"] is not None else 0.0
                results.append(
                    VectorSearchResult(
                        id=str(row["id"]),
                        score=score,
                        payload=payload,
                    )
                )
            return results
        except Exception as e:
            logger.error(f"Error searching PgVectorStore table '{self.table_name}': {e}", exc_info=True)
            return []

    def get_stats(self) -> Dict[str, Any]:
        """Returns table statistics including row count and backend mode."""
        try:
            with self.engine.connect() as conn:
                count = conn.execute(text(f"SELECT count(*) FROM {self.table_name}")).scalar() or 0
            return {
                "backend": "pgvector",
                "mode": self.mode,
                "collection_name": self.collection_name,
                "table_name": self.table_name,
                "exists": True,
                "points_count": int(count),
                "vectors_count": int(count),
                "location": self.location,
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
            }

    def health_check(self) -> Tuple[bool, str]:
        """Validates connection and presence of the vector documents table."""
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1;"))
                conn.execute(text(f"SELECT 1 FROM {self.table_name} LIMIT 1;"))
            return True, f"PgVectorStore ({self.location}) is healthy; table '{self.table_name}' verified"
        except Exception as e:
            return False, f"PgVectorStore health check failed: {e}"

    def close(self):
        """Disposes underlying database handles if necessary."""
        pass
