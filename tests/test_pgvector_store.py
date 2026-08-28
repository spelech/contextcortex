"""Tests for PgVectorStore and its registration in VectorStoreManager."""

import os
import json
import pytest
from unittest.mock import MagicMock, patch, call
from sqlalchemy import create_engine, text

from app.services.vector_store.base import VectorStore, VectorDocument, VectorSearchResult
from app.services.vector_store import manager as vs_manager
from app.services.vector_store.manager import VectorStoreManager, SUPPORTED_PROVIDERS


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

    def test_ensure_collection_handles_extension_permission_warning(self):
        from app.services.vector_store.pgvector_store import PgVectorStore
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        def execute_side_effect(statement, *args, **kwargs):
            if "CREATE EXTENSION" in str(statement):
                raise Exception("permission denied to create extension")
            return MagicMock()

        mock_conn.execute.side_effect = execute_side_effect
        store = PgVectorStore(engine=mock_engine, auto_init=False)
        success = store.ensure_collection()
        assert success is True

    def test_ensure_collection_failure(self):
        from app.services.vector_store.pgvector_store import PgVectorStore
        mock_engine = MagicMock()
        mock_engine.connect.side_effect = Exception("DB Connection Error")
        store = PgVectorStore(engine=mock_engine, auto_init=False)
        assert store.ensure_collection() is False

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
        assert "DB Connection Refused" in msg

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
        assert "ON CONFLICT (id) DO UPDATE" in statement
        assert len(params) == 2
        assert params[0]["id"] == "doc-1"
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
        assert store.upsert_documents([VectorDocument(id="1", text="abc")]) is False

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
        assert "DELETE FROM vector_documents WHERE path = :path" in stmt
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
        assert "DELETE FROM vector_documents WHERE repo = :repo" in stmt
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
