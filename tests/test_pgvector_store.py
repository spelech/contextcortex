"""Tests for PgVectorStore and its registration in VectorStoreManager."""

import json
import os
import pytest
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine, text
from sqlalchemy.dialects import postgresql

from app.services.vector_store.base import VectorStore, VectorDocument, VectorSearchResult
from app.services.vector_store import manager as vs_manager
from app.services.vector_store.manager import VectorStoreManager, SUPPORTED_PROVIDERS


@pytest.fixture(autouse=True)
def embedding_dimension():
    with patch("app.services.vector_store.pgvector_store.get_dense_dim", return_value=384):
        yield


class TestPgVectorStoreRegistration:
    """Tests ensuring PgVectorStore is registered and dispatched by VectorStoreManager."""

    def test_import_and_supported_providers(self):
        from app.services.vector_store.pgvector_store import PgVectorStore
        from app.services.vector_store import PgVectorStore as ExportedPgVectorStore
        assert ExportedPgVectorStore is PgVectorStore
        assert issubclass(PgVectorStore, VectorStore)
        for alias in ("postgres", "pgvector", "postgresql"):
            assert alias in SUPPORTED_PROVIDERS

    @pytest.mark.parametrize("provider", ["pgvector", "postgres", "postgresql"])
    def test_create_store_provider_aliases(self, provider):
        from app.services.vector_store.pgvector_store import PgVectorStore
        with patch.object(PgVectorStore, "ensure_collection", return_value=True):
            store = VectorStoreManager._create_store({
                "provider": provider,
                "url": "postgresql+psycopg://user:pass@localhost:5432/db",
                "collection": "custom_pg_coll",
            })
            assert isinstance(store, PgVectorStore)
            assert store.collection_name == "custom_pg_coll"
            assert store.table_name == "vector_documents"
            assert store.dimension == 384
            assert store.mode == "postgres"
            assert store.get_capabilities() == {
                "search_modes": ["hybrid", "semantic", "lexical"],
                "supports_weighting": True,
            }

    def test_invalid_search_mode_raises(self):
        from app.services.vector_store.pgvector_store import PgVectorStore
        store = PgVectorStore(engine=MagicMock(), auto_init=False)
        with pytest.raises(ValueError, match="Search mode 'invalid_mode' is not supported"):
            store.search("capabilities test", search_mode="invalid_mode")
        assert store.search("") == []
        assert store.search("   ") == []


class TestPgVectorStoreSchemaAndSearchContracts:
    """Focused contract tests for PostgreSQL-specific DDL and hybrid/lexical SQL generation."""

    def test_ensure_collection_ddl_and_extension_permissions(self):
        from app.services.vector_store.pgvector_store import PgVectorStore
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.scalar.return_value = None
        mock_conn.execute.return_value.fetchone.return_value = None
        mock_conn.execute.return_value.fetchall.return_value = [("collection_name",), ("id",)]

        store = PgVectorStore(engine=mock_engine, auto_init=False)
        assert store.ensure_collection() is True
        full_sql = " ".join(str(c[0][0]) for c in mock_conn.execute.call_args_list)
        assert "CREATE EXTENSION IF NOT EXISTS vector" in full_sql
        assert "CREATE TABLE IF NOT EXISTS vector_documents" in full_sql
        assert "idx_vector_documents_embedding" in full_sql

    def test_migration_and_dimension_mismatch_guard(self):
        from app.services.vector_store.pgvector_store import PgVectorStore

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_engine.dialect = postgresql.dialect()
        mock_conn.execute.return_value.fetchall.return_value = [("id",)]
        mock_conn.execute.return_value.fetchone.side_effect = [(384,), ("vector_documents_pkey",)]

        store = PgVectorStore(engine=mock_engine, collection_name="collection_test", auto_init=False)
        assert store.ensure_collection() is True

        # Dimension mismatch on populated table raises ValueError
        mock_conn.execute.return_value.fetchall.return_value = [("collection_name", "id")]
        mock_conn.execute.return_value.fetchone.side_effect = None
        mock_conn.execute.return_value.fetchone.return_value = (1536,)
        with pytest.raises(ValueError, match="dimension mismatch.*explicit rebuild"):
            store.ensure_collection()

    def test_search_hybrid_and_lexical_fusion(self):
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
        with patch("app.services.vector_store.pgvector_store.get_dense_embedding", return_value=[0.1] * 384):
            results = store.search(
                query_text="hybrid match",
                search_mode="hybrid",
                dense_weight=0.7,
                limit=5,
            )

        assert len(results) == 1
        assert results[0].id == "doc-hyb-1"
        assert results[0].score == pytest.approx(0.86)
        assert results[0].dense_score == pytest.approx(0.80)
        assert results[0].sparse_score == pytest.approx(1.0)


class TestPgVectorCollectionIsolation:
    """Integration tests using a real SQLite engine to verify collection isolation and CRUD."""

    def test_collection_isolation_reads_writes_deletes(self):
        from app.services.vector_store.pgvector_store import PgVectorStore

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

        doc_a = VectorDocument(
            id="doc-1",
            text="Document for collection A",
            dense_vector=[0.1] * 384,
            repo="repo_a",
            path="file_a.py",
            tags=["core"],
            metadata={"extra": "val"},
        )
        assert store_a.upsert_documents([doc_a]) is True
        assert store_a.upsert_documents([]) is True
        assert store_a.health_check()[0] is True

        assert store_a.get_stats()["points_count"] == 1
        assert store_b.get_stats()["points_count"] == 0

        # Deletion in B does not purge A's document
        assert store_b.delete_by_path("file_a.py") is True
        assert store_a.get_stats()["points_count"] == 1
        assert store_b.delete_by_repo("repo_a") is True
        assert store_a.get_stats()["points_count"] == 1
        assert store_b.delete_collection() is True
        assert store_a.get_stats()["points_count"] == 1

        # Deletion in A purges A's document
        assert store_a.delete_by_repo("repo_a") is True
        assert store_a.get_stats()["points_count"] == 0
        store_a.close()


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

        assert build_authenticated_url(ssh_url, token=None) == ssh_url
        assert build_authenticated_url(ssh_scheme_url, token=None) == ssh_scheme_url

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
