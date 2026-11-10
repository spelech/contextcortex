"""Tests for PgVectorStore and its registration in VectorStoreManager."""

import os
import json
import pytest
from unittest.mock import MagicMock, patch, call
from sqlalchemy import create_engine, text
from sqlalchemy.dialects import postgresql

from app.services.vector_store.base import VectorStore, VectorDocument, VectorSearchResult
from app.services.vector_store import manager as vs_manager
from app.services.vector_store.manager import VectorStoreManager, SUPPORTED_PROVIDERS


@pytest.fixture(autouse=True)
def embedding_dimension():
    # These unit tests exercise the store, not an external embedding service.
    with patch("app.services.vector_store.pgvector_store.get_dense_dim", return_value=384):
        yield


class TestPgVectorStoreImports:
    """Tests ensuring PgVectorStore is importable and registered."""

    def test_import_pgvector_store(self):
        from app.services.vector_store.pgvector_store import PgVectorStore
        from app.services.vector_store import PgVectorStore as ExportedPgVectorStore
        assert PgVectorStore is not None
        assert ExportedPgVectorStore is PgVectorStore
        assert issubclass(PgVectorStore, VectorStore)

    def test_manager_supported_providers_includes_postgres_and_pgvector(self):
        assert "postgres" in SUPPORTED_PROVIDERS
        assert "pgvector" in SUPPORTED_PROVIDERS
        assert "postgresql" in SUPPORTED_PROVIDERS


class TestPgVectorStoreLifecycle:
    """Tests for PgVectorStore initialization, schema creation, and health check."""

    def test_initialization_defaults(self):
        from app.services.vector_store.pgvector_store import PgVectorStore
        with patch.object(PgVectorStore, "ensure_collection", return_value=True):
            store = PgVectorStore(database_url="postgresql+psycopg://user:pass@localhost/testdb", auto_init=False)
            assert store.table_name == "vector_documents"
            assert store.dimension == 384
            assert store.collection_name == "knowledge_rag_v1"
            assert store.mode == "postgres"

    def test_ensure_collection_executes_ddl(self):
        from app.services.vector_store.pgvector_store import PgVectorStore
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.scalar.return_value = None
        mock_conn.execute.return_value.fetchone.return_value = None
        mock_conn.execute.return_value.fetchall.return_value = [("collection_name",), ("id",)]

        store = PgVectorStore(engine=mock_engine, auto_init=False)
        success = store.ensure_collection()

        assert success is True
        assert mock_conn.execute.called
        executed_sqls = [str(call_args[0][0]) for call_args in mock_conn.execute.call_args_list]
        full_sql = " ".join(executed_sqls)
        assert "CREATE EXTENSION IF NOT EXISTS vector" in full_sql
        assert "CREATE TABLE IF NOT EXISTS vector_documents" in full_sql
        assert "idx_vector_documents_embedding" in full_sql
        assert "hnsw" in full_sql.lower()
        assert "vector_cosine_ops" in full_sql

    @pytest.mark.parametrize("installed", [False, True])
    def test_ensure_collection_extension_permissions(self, installed):
        from app.services.vector_store.pgvector_store import PgVectorStore
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        def execute_side_effect(statement, *args, **kwargs):
            if "CREATE EXTENSION" in str(statement):
                raise PermissionError("permission denied to create extension")
            result = MagicMock()
            result.scalar.return_value = 1 if installed else None
            result.fetchone.return_value = None
            result.fetchall.return_value = [("collection_name",), ("id",)]
            return result

        mock_conn.execute.side_effect = execute_side_effect
        store = PgVectorStore(engine=mock_engine, auto_init=False)
        if installed:
            assert store.ensure_collection() is True
        else:
            with pytest.raises(RuntimeError, match="initialize") as error:
                store.ensure_collection()
            assert isinstance(error.value.__cause__, PermissionError)

    def test_ensure_collection_failure(self):
        from app.services.vector_store.pgvector_store import PgVectorStore
        mock_engine = MagicMock()
        mock_engine.connect.side_effect = Exception("DB Connection Error")
        store = PgVectorStore(engine=mock_engine, auto_init=False)
        with pytest.raises(RuntimeError, match="initialize") as error:
            store.ensure_collection()
        assert str(error.value.__cause__) == "DB Connection Error"

    def test_health_check_success(self):
        from app.services.vector_store.pgvector_store import PgVectorStore
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.scalar.return_value = 1

        store = PgVectorStore(engine=mock_engine, auto_init=False)
        healthy, msg = store.health_check()
        assert healthy is True
        assert "healthy" in msg.lower()

    def test_health_check_failure(self):
        from app.services.vector_store.pgvector_store import PgVectorStore
        mock_engine = MagicMock()
        mock_engine.connect.side_effect = Exception("DB Connection Refused")

        store = PgVectorStore(engine=mock_engine, auto_init=False)
        healthy, msg = store.health_check()
        assert healthy is False
        assert "health check failed" in msg.lower()

    def test_get_capabilities_and_search_mode_validation(self):
        from app.services.vector_store.pgvector_store import PgVectorStore
        mock_engine = MagicMock()
        store = PgVectorStore(engine=mock_engine, auto_init=False)

        caps = store.get_capabilities()
        assert caps == {"search_modes": ["hybrid", "semantic", "lexical"], "supports_weighting": True}

        # Invalid mode raises ValueError
        with pytest.raises(ValueError) as exc_info:
            store.search("capabilities test", search_mode="invalid_mode")
        assert "Search mode 'invalid_mode' is not supported by PgVector vector store" in str(exc_info.value)

    def test_get_stats_success(self):
        from app.services.vector_store.pgvector_store import PgVectorStore
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.scalar.return_value = 42

        store = PgVectorStore(engine=mock_engine, auto_init=False)
        stats = store.get_stats()
        assert stats["backend"] == "pgvector"
        assert stats["points_count"] == 42
        assert stats["vectors_count"] == 42
        assert stats["exists"] is True

    def test_get_stats_failure(self):
        from app.services.vector_store.pgvector_store import PgVectorStore
        mock_engine = MagicMock()
        mock_engine.connect.side_effect = Exception("Table not found")

        store = PgVectorStore(engine=mock_engine, auto_init=False)
        stats = store.get_stats()
        assert stats["backend"] == "pgvector"
        assert stats["exists"] is False
        assert "error" in stats

    def test_close_method(self):
        from app.services.vector_store.pgvector_store import PgVectorStore
        mock_engine = MagicMock()
        store = PgVectorStore(engine=mock_engine, auto_init=False)
        store.close()  # Should not raise


class TestPgVectorStoreUpsertAndSearch:
    """Tests for document upserts, deletions, and cosine similarity search."""

    def test_upsert_documents_with_vector_documents(self):
        from app.services.vector_store.pgvector_store import PgVectorStore
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        store = PgVectorStore(engine=mock_engine, auto_init=False)
        docs = [
            VectorDocument(
                id="doc-1",
                text="def hello_world(): pass",
                dense_vector=[0.1] * 384,
                repo="contextcortex",
                path="app/hello.py",
                rel_path="hello.py",
                title="Hello Module",
                folder="app",
                category="code",
                tags=["python", "core"],
                doc_type="code",
                language="python",
                start_line=1,
                end_line=5,
                github_url="https://github.com/repo/blob/main/hello.py",
                permalink_url="https://github.com/repo/blob/main/hello.py",
                metadata={"extra_field": "val1"},
            ),
            VectorDocument(
                id="doc-2",
                text="API route definition",
                dense_vector=[0.2] * 384,
                repo="contextcortex",
                path="app/api.py",
                tags=["api"],
            ),
        ]

        success = store.upsert_documents(docs, batch_size=50)
        assert success is True
        assert mock_conn.execute.called
        assert mock_conn.commit.called

        executed_call = mock_conn.execute.call_args
        statement = str(executed_call[0][0])
        params = executed_call[0][1]

        assert "INSERT INTO vector_documents" in statement
        assert "ON CONFLICT (collection_name, id) DO UPDATE" in statement
        assert len(params) == 2
        assert params[0]["id"] == "doc-1"
        assert params[0]["collection_name"] == "knowledge_rag_v1"
        assert params[0]["repo"] == "contextcortex"
        assert params[0]["language"] == "python"
        assert params[0]["tags"] == json.dumps(["python", "core"])
        assert "extra_field" in json.loads(params[0]["payload"])
        assert params[1]["id"] == "doc-2"

    def test_upsert_documents_with_dicts(self):
        from app.services.vector_store.pgvector_store import PgVectorStore
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        store = PgVectorStore(engine=mock_engine, auto_init=False)
        raw_docs = [
            {
                "id": "doc-dict-1",
                "text": "dict content",
                "dense_vector": [0.05] * 384,
                "repo": "dict-repo",
                "tags": ["dict-tag"],
                "custom_prop": 123,
            }
        ]

        success = store.upsert_documents(raw_docs)
        assert success is True
        assert mock_conn.execute.called

        executed_call = mock_conn.execute.call_args
        params = executed_call[0][1]
        assert params[0]["id"] == "doc-dict-1"
        assert params[0]["repo"] == "dict-repo"
        payload = json.loads(params[0]["payload"])
        assert payload["custom_prop"] == 123
        assert payload["content"] == "dict content"

    def test_upsert_generates_embeddings_when_missing(self):
        from app.services.vector_store.pgvector_store import PgVectorStore
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        store = PgVectorStore(engine=mock_engine, auto_init=False)
        doc = VectorDocument(id="doc-no-emb", text="Sample text without embedding")

        with patch("app.services.vector_store.pgvector_store.get_dense_embedding", return_value=[0.3] * 384) as mock_emb:
            store.upsert_documents([doc])
            mock_emb.assert_called_once_with("Sample text without embedding")

        executed_call = mock_conn.execute.call_args
        params = executed_call[0][1]
        assert params[0]["id"] == "doc-no-emb"
        assert params[0]["embedding"] == str([0.3] * 384)

    def test_upsert_empty_list_noop(self):
        from app.services.vector_store.pgvector_store import PgVectorStore
        mock_engine = MagicMock()
        store = PgVectorStore(engine=mock_engine, auto_init=False)
        assert store.upsert_documents([]) is True
        assert not mock_engine.connect.called

    def test_upsert_failure_returns_false(self):
        from app.services.vector_store.pgvector_store import PgVectorStore
        mock_engine = MagicMock()
        mock_engine.connect.side_effect = Exception("Write error")
        store = PgVectorStore(engine=mock_engine, auto_init=False)
        assert store.upsert_documents([VectorDocument(id="1", text="abc", dense_vector=[0.1] * 384)]) is False

    def test_search_executes_cosine_distance_query(self):
        from app.services.vector_store.pgvector_store import PgVectorStore
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        mock_conn.execute.return_value.mappings.return_value.fetchall.return_value = [
            {"id": "doc-1", "score": 0.92, "payload": json.dumps({"content": "hello world", "repo": "contextcortex"})},
            {"id": "doc-2", "score": 0.85, "payload": {"content": "api route", "repo": "contextcortex"}},
        ]

        store = PgVectorStore(engine=mock_engine, auto_init=False)
        with patch("app.services.vector_store.pgvector_store.get_dense_embedding", return_value=[0.1] * 384):
            results = store.search(
                query_text="hello",
                doc_type="code",
                repo="contextcortex",
                language="python",
                category="backend",
                tag="core",
                limit=5,
                search_mode="semantic",
            )

        assert len(results) == 2
        assert isinstance(results[0], VectorSearchResult)
        assert results[0].id == "doc-1"
        assert results[0].score == 0.92
        assert results[0].payload["content"] == "hello world"

        executed_call = mock_conn.execute.call_args
        sql_stmt = str(executed_call[0][0])
        params = executed_call[0][1]

        assert "<=>" in sql_stmt
        assert "CAST(:query_vec AS vector)" in sql_stmt
        assert "CAST(:tag_json AS jsonb)" in sql_stmt
        assert "ORDER BY embedding <=> CAST(:query_vec AS vector)" in sql_stmt
        assert "LIMIT :limit" in sql_stmt
        assert params["repo"] == "contextcortex"
        assert params["doc_type"] == "code"
        assert params["language"] == "python"
        assert params["category"] == "backend"
        assert params["limit"] == 5

    def test_search_lexical_executes_fts_without_dense_embedding(self):
        from app.services.vector_store.pgvector_store import PgVectorStore
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        mock_conn.execute.return_value.mappings.return_value.fetchall.return_value = [
            {"id": "doc-lex-1", "sparse_score": 0.75, "payload": {"content": "exact_identifier_match", "repo": "contextcortex"}},
            {"id": "doc-lex-2", "sparse_score": 0.375, "payload": {"content": "partial_match", "repo": "contextcortex"}},
        ]

        store = PgVectorStore(engine=mock_engine, auto_init=False)
        with patch("app.services.vector_store.pgvector_store.get_dense_embedding") as mock_emb:
            results = store.search(
                query_text="exact_identifier_match",
                search_mode="lexical",
                limit=5,
            )
            mock_emb.assert_not_called()

        assert len(results) == 2
        assert results[0].id == "doc-lex-1"
        assert results[0].score == 1.0
        assert results[0].sparse_score == 1.0
        assert results[1].id == "doc-lex-2"
        assert results[1].score == 0.5

        executed_call = mock_conn.execute.call_args
        sql_stmt = str(executed_call[0][0])
        params = executed_call[0][1]
        assert "to_tsvector('simple'" in sql_stmt
        assert "websearch_to_tsquery('simple', :query_text)" in sql_stmt
        assert "ts_rank_cd" in sql_stmt
        assert params["query_text"] == "exact_identifier_match"

    def test_search_hybrid_executes_weighted_fusion(self):
        from app.services.vector_store.pgvector_store import PgVectorStore
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        dense_result = MagicMock()
        dense_result.mappings.return_value.fetchall.return_value = [
            {"id": "doc-hyb-1", "score": 0.80, "payload": {"content": "hybrid match", "repo": "contextcortex"}},
        ]
        lexical_result = MagicMock()
        lexical_result.mappings.return_value.fetchall.return_value = [
            {"id": "doc-hyb-1", "sparse_score": 0.50, "payload": {"content": "hybrid match", "repo": "contextcortex"}},
        ]
        mock_conn.execute.side_effect = [dense_result, lexical_result]

        store = PgVectorStore(engine=mock_engine, auto_init=False)
        with patch("app.services.vector_store.pgvector_store.get_dense_embedding", return_value=[0.1] * 384) as mock_emb:
            results = store.search(
                query_text="hybrid match",
                search_mode="hybrid",
                dense_weight=0.7,
                limit=5,
            )
            mock_emb.assert_called_once_with("hybrid match")

        assert len(results) == 1
        assert results[0].id == "doc-hyb-1"
        # combined = 0.7 * 0.80 + 0.3 * 1.0 (normalized max sparse_score) = 0.86
        assert results[0].score == pytest.approx(0.86)
        assert results[0].dense_score == pytest.approx(0.80)
        assert results[0].sparse_score == pytest.approx(1.0)
        assert mock_conn.execute.call_count == 2

    def test_search_empty_query_returns_empty(self):
        from app.services.vector_store.pgvector_store import PgVectorStore
        mock_engine = MagicMock()
        store = PgVectorStore(engine=mock_engine, auto_init=False)
        assert store.search("") == []
        assert store.search("   ") == []

    def test_search_error_returns_empty_list(self):
        from app.services.vector_store.pgvector_store import PgVectorStore
        mock_engine = MagicMock()
        mock_engine.connect.side_effect = Exception("Query execution error")
        store = PgVectorStore(engine=mock_engine, auto_init=False)
        with patch("app.services.vector_store.pgvector_store.get_dense_embedding", return_value=[0.1] * 384):
            assert store.search("hello") == []

    def test_delete_by_path(self):
        from app.services.vector_store.pgvector_store import PgVectorStore
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        store = PgVectorStore(engine=mock_engine, auto_init=False)
        success = store.delete_by_path("/app/old_file.py")
        assert success is True
        assert mock_conn.commit.called

        executed_call = mock_conn.execute.call_args
        stmt = str(executed_call[0][0])
        params = executed_call[0][1]
        assert "DELETE FROM vector_documents WHERE collection_name = :collection_name AND path = :path" in stmt
        assert params["collection_name"] == "knowledge_rag_v1"
        assert params["path"] == "/app/old_file.py"

    def test_delete_by_path_failure(self):
        from app.services.vector_store.pgvector_store import PgVectorStore
        mock_engine = MagicMock()
        mock_engine.connect.side_effect = Exception("Delete error")
        store = PgVectorStore(engine=mock_engine, auto_init=False)
        assert store.delete_by_path("/app/old_file.py") is False

    def test_delete_by_repo(self):
        from app.services.vector_store.pgvector_store import PgVectorStore
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        store = PgVectorStore(engine=mock_engine, auto_init=False)
        success = store.delete_by_repo("deprecated_repo")
        assert success is True
        assert mock_conn.commit.called

        executed_call = mock_conn.execute.call_args
        stmt = str(executed_call[0][0])
        params = executed_call[0][1]
        assert "DELETE FROM vector_documents WHERE collection_name = :collection_name AND repo = :repo" in stmt
        assert params["collection_name"] == "knowledge_rag_v1"
        assert params["repo"] == "deprecated_repo"

    def test_delete_by_repo_failure(self):
        from app.services.vector_store.pgvector_store import PgVectorStore
        mock_engine = MagicMock()
        mock_engine.connect.side_effect = Exception("Delete error")
        store = PgVectorStore(engine=mock_engine, auto_init=False)
        assert store.delete_by_repo("deprecated_repo") is False


class TestVectorStoreManagerPgVectorDispatch:
    """Tests for VectorStoreManager dynamic dispatch with pgvector/postgres."""

    def test_create_store_pgvector_provider(self):
        from app.services.vector_store.pgvector_store import PgVectorStore
        with patch.object(PgVectorStore, "ensure_collection", return_value=True):
            store = VectorStoreManager._create_store({
                "provider": "pgvector",
                "url": "postgresql+psycopg://user:pass@localhost:5432/db",
                "collection": "custom_pg_coll",
            })
            assert isinstance(store, PgVectorStore)
            assert store.collection_name == "custom_pg_coll"

    def test_create_store_postgres_provider(self):
        from app.services.vector_store.pgvector_store import PgVectorStore
        with patch.object(PgVectorStore, "ensure_collection", return_value=True):
            store = VectorStoreManager._create_store({
                "provider": "postgres",
                "url": "postgresql+psycopg://user:pass@localhost:5432/db",
            })
            assert isinstance(store, PgVectorStore)

    def test_create_store_postgresql_provider(self):
        from app.services.vector_store.pgvector_store import PgVectorStore
        with patch.object(PgVectorStore, "ensure_collection", return_value=True):
            store = VectorStoreManager._create_store({
                "provider": "postgresql",
                "url": "postgresql+psycopg://user:pass@localhost:5432/db",
            })
            assert isinstance(store, PgVectorStore)

    def test_test_connection_pgvector(self):
        from app.services.vector_store.pgvector_store import PgVectorStore
        with patch.object(PgVectorStore, "ensure_collection", return_value=True), \
             patch.object(PgVectorStore, "health_check", return_value=(True, "PgVector is healthy")):
            ok, msg = vs_manager.test_vector_store_connection(
                provider="pgvector",
                url="postgresql+psycopg://user:pass@localhost:5432/db",
            )
            assert ok is True
            assert "healthy" in msg.lower()


class TestPgVectorCollectionIsolation:
    """Integration style tests using sqlite/mock database engines to test isolation between collections."""

    def test_collection_isolation_reads_writes_deletes(self):
        """Test that collection_a writes/deletes do not affect collection_b in the same table."""
        from app.services.vector_store.pgvector_store import PgVectorStore

        # Create an in-memory SQLite engine simulating PgVectorStore operations
        engine = create_engine("sqlite:///:memory:")
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE vector_documents (
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
                    embedding TEXT,
                    payload JSONB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (collection_name, id)
                );
            """))
            conn.commit()

        store_a = PgVectorStore(engine=engine, collection_name="collection_a", auto_init=False)
        store_b = PgVectorStore(engine=engine, collection_name="collection_b", auto_init=False)

        # 1. Insert doc into collection A
        doc_a = VectorDocument(
            id="doc-1",
            text="Document for collection A",
            dense_vector=[0.1] * 384,
            repo="repo_a",
            path="file_a.py",
        )
        assert store_a.upsert_documents([doc_a]) is True

        # 2. Verify stats for A and B
        stats_a = store_a.get_stats()
        stats_b = store_b.get_stats()
        assert stats_a["points_count"] == 1
        assert stats_b["points_count"] == 0

        # 3. Verify search in collection B returns empty
        with patch("app.services.vector_store.pgvector_store.get_dense_embedding", return_value=[0.1] * 384):
            # SQLite does not support pgvector <=> syntax, so mock search execute query or test directly
            with patch.object(engine, "connect") as mock_conn:
                m = MagicMock()
                mock_conn.return_value.__enter__.return_value = m
                m.execute.return_value.mappings.return_value.fetchall.return_value = []
                results_b = store_b.search("Document")
                assert len(results_b) == 0

        # 4. Deletion in B does not purge A's document
        assert store_b.delete_by_path("file_a.py") is True
        assert store_a.get_stats()["points_count"] == 1

        assert store_b.delete_by_repo("repo_a") is True
        assert store_a.get_stats()["points_count"] == 1

        # Deleting collection B leaves collection A intact
        assert store_b.delete_collection() is True
        assert store_a.get_stats()["points_count"] == 1

        # Deletion in A purges A's document
        assert store_a.delete_by_repo("repo_a") is True
        assert store_a.get_stats()["points_count"] == 0

    def test_migration_and_pk_update(self):
        """Test schema migration for legacy table without collection_name column."""
        from app.services.vector_store.pgvector_store import PgVectorStore

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        mock_engine.dialect = postgresql.dialect()
        mock_conn.execute.return_value.fetchall.return_value = [("id",)]
        mock_conn.execute.return_value.fetchone.side_effect = [(384,), ("vector_documents_pkey",)]

        store = PgVectorStore(engine=mock_engine, collection_name="collection_test", auto_init=False)
        success = store.ensure_collection()
        assert success is True

        executed_sqls = [str(call_args[0][0]) for call_args in mock_conn.execute.call_args_list]
        full_sql = " ".join(executed_sqls)

        assert "ADD COLUMN IF NOT EXISTS collection_name" in full_sql
        assert "UPDATE vector_documents SET collection_name = 'knowledge_rag_v1' WHERE collection_name IS NULL" in full_sql
        assert "ALTER TABLE vector_documents DROP CONSTRAINT vector_documents_pkey" in full_sql
        assert "ALTER TABLE vector_documents ADD PRIMARY KEY (collection_name, id)" in full_sql

    def test_dimension_mismatch_requires_explicit_rebuild(self):
        """A populated shared table cannot be silently recreated."""
        from app.services.vector_store.pgvector_store import PgVectorStore

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        # Mock dimension query returning 1536d while store uses 384d
        mock_conn.execute.return_value.fetchall.return_value = [("collection_name", "id")]
        mock_conn.execute.return_value.fetchone.return_value = (1536,)

        store = PgVectorStore(engine=mock_engine, dimension=384, auto_init=False)
        with pytest.raises(ValueError, match="dimension mismatch.*explicit rebuild"):
            store.ensure_collection()


class TestGitSshAndGlabSupport:
    """Tests for native SSH git URL preservation and GitLab `glab` CLI token fallback."""

    def test_is_ssh_git_url_and_build_authenticated_url_preserves_ssh(self):
        from app.services.git_manager import is_ssh_git_url, build_authenticated_url

        ssh_url = "git@gitlab.corp.example.com:platform/service.git"
        ssh_scheme_url = "ssh://git@gitlab.corp.example.com/platform/service.git"
        https_url = "https://gitlab.corp.example.com/platform/service.git"

        assert is_ssh_git_url(ssh_url) is True
        assert is_ssh_git_url(ssh_scheme_url) is True
        assert is_ssh_git_url(https_url) is False

        # Without HTTP token/username, SSH URL is preserved so user's SSH keys are used
        assert build_authenticated_url(ssh_url, token=None) == ssh_url
        assert build_authenticated_url(ssh_scheme_url, token=None) == ssh_scheme_url

        # When an explicit HTTP token IS provided, it converts to authenticated HTTPS
        auth_https = build_authenticated_url(ssh_url, token="glpat-12345", provider="gitlab")
        assert auth_https == "https://oauth2:glpat-12345@gitlab.corp.example.com/platform/service.git"

    def test_get_remote_head_sha_uses_ssh_url_when_no_token(self):
        from app.services.git_manager import get_remote_head_sha

        ssh_url = "git@gitlab.corp.example.com:platform/service.git"
        mock_res = MagicMock(returncode=0, stdout="deadbeef1234567890\trefs/heads/main\n")

        with patch("subprocess.run", return_value=mock_res) as mock_run:
            sha = get_remote_head_sha(ssh_url, branch="main")
            assert sha == "deadbeef1234567890"
            called_cmd = mock_run.call_args[0][0]
            assert called_cmd[:3] == ["git", "ls-remote", ssh_url]

    def test_glab_cli_token_fallback_for_gitlab(self):
        from app.services.database.credentials import get_effective_git_token

        mock_proc = MagicMock(returncode=0, stdout="glpat-from-glab-cli\n")
        with patch("app.services.database.credentials.get_git_host_credential", return_value=None), \
             patch("app.services.database.credentials.get_metadata", return_value=None), \
             patch.dict(os.environ, {}, clear=False), \
             patch("shutil.which", return_value="/usr/bin/glab"), \
             patch("subprocess.run", return_value=mock_proc) as mock_run:
            os.environ.pop("GITLAB_TOKEN", None)
            os.environ.pop("GL_TOKEN", None)
            tok, user, source = get_effective_git_token("https://gitlab.corp.example.com/group/repo.git")
            assert tok == "glpat-from-glab-cli"
            assert "glab" in source
            assert mock_run.called

