import os
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.services.database.engine import get_db_engine, init_db
from app.services.database import get_db_connection, set_embedding_db_config, clear_indexing_metadata
from app.services.embeddings import (
    update_embedding_config, get_embedding_config, init_embeddings
)
from app.services.vector_store import VectorStoreManager, QdrantVectorStore
from app.services.vector_store.base import VectorDocument
from main import app

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_test_environment(tmp_path, monkeypatch):
    db_file = tmp_path / "test_transition.db"
    db_url = f"sqlite:///{db_file}"
    vs_dir = tmp_path / "qdrant"
    vs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("QDRANT_STORAGE_PATH", str(vs_dir))
    monkeypatch.setenv("QDRANT_PREFER_REMOTE", "false")
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("EMBEDDING_PROVIDER", "local")
    monkeypatch.setenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
    engine = get_db_engine(db_url, reset=True)
    init_db(engine=engine)
    set_embedding_db_config(provider="local", dense_model="BAAI/bge-small-en-v1.5")
    init_embeddings(provider="local", dense_model="BAAI/bge-small-en-v1.5")
    VectorStoreManager.reset_instance()
    yield
    VectorStoreManager.reset_instance()


def test_update_embedding_config_rejection_when_index_has_content(monkeypatch):
    """Verifies that changing dense model/dimension without rebuild_index=True raises ValueError if index has content."""
    # Populate dummy indexed file and vector store point
    store = VectorStoreManager.get_vector_store()
    store.upsert_documents([
        VectorDocument(
            id="doc1",
            text="sample text",
            dense_vector=[0.1] * 384,
            repo="local",
            doc_type="doc",
            path="/tmp/doc1.txt"
        )
    ])
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO indexed_files (filepath, repo, doc_type, language, mtime) VALUES (?, ?, ?, ?, ?)",
            ("/tmp/doc1.txt", "local", "doc", "txt", 1.0)
        )
        conn.commit()

    # Mock candidate probe dimension to be 1536d (different from active 384d)
    with patch("app.services.embeddings.get_dense_dim_for_config", return_value=1536):
        with pytest.raises(ValueError) as exc_info:
            update_embedding_config(
                provider="api",
                dense_model="openai/text-embedding-3-small",
                rebuild_index=False
            )
        assert "Explicit rebuild confirmation is required" in str(exc_info.value)

    # Confirm active configuration in DB was NOT changed
    active_cfg = get_embedding_config()
    assert active_cfg["dense_model"] == "BAAI/bge-small-en-v1.5"


def test_api_save_embedding_settings_rejection_returns_400(monkeypatch):
    """Verifies POST /admin/api/settings/embedding returns HTTP 400 when change is rejected."""
    store = VectorStoreManager.get_vector_store()
    store.upsert_documents([
        VectorDocument(
            id="doc2",
            text="another text",
            dense_vector=[0.2] * 384,
            repo="local",
            doc_type="doc",
            path="/tmp/doc2.txt"
        )
    ])
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO indexed_files (filepath, repo, doc_type, language, mtime) VALUES (?, ?, ?, ?, ?)",
            ("/tmp/doc2.txt", "local", "doc", "txt", 1.0)
        )
        conn.commit()

    with patch("app.services.embeddings.get_dense_dim_for_config", return_value=1536):
        res = client.post("/admin/api/settings/embedding", json={
            "provider": "api",
            "dense_model": "openai/text-embedding-3-small",
            "rebuild_index": False
        })
        assert res.status_code == 400
        data = res.json()
        assert "Explicit rebuild confirmation is required" in data["error"]


def test_update_embedding_config_success_with_rebuild(monkeypatch):
    """Verifies that update_embedding_config succeeds when rebuild_index=True and triggers metadata reset."""
    store = VectorStoreManager.get_vector_store()
    store.upsert_documents([
        VectorDocument(
            id="doc3",
            text="text3",
            dense_vector=[0.3] * 384,
            repo="repo-1",
            doc_type="code",
            path="/tmp/code1.py"
        )
    ])
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO indexed_files (filepath, repo, doc_type, language, mtime) VALUES (?, ?, ?, ?, ?)",
            ("/tmp/code1.py", "repo-1", "code", "py", 1.0)
        )
        conn.commit()

    with patch("app.services.embeddings.get_dense_dim_for_config", return_value=1536), \
         patch("app.services.embeddings.get_dense_embeddings_batch", return_value=[[0.1] * 1536]), \
         patch("app.services.indexing.run_full_indexing") as mock_reindex:

        cfg = update_embedding_config(
            provider="api",
            dense_model="openai/text-embedding-3-small",
            rebuild_index=True
        )

        assert cfg["provider"] == "api"
        assert cfg["dense_model"] == "openai/text-embedding-3-small"

        # Verify relational metadata was cleared for rebuild
        with get_db_connection() as conn:
            cnt = conn.execute("SELECT count(*) FROM indexed_files").fetchone()[0]
            assert cnt == 0


def test_dimension_mismatch_during_search_raises_explicit_error(monkeypatch):
    """Verifies that vector search with mismatched query vector dimension raises ValueError and returns HTTP 400."""
    store = VectorStoreManager.get_vector_store()
    # Collection initialized with 384d
    store.upsert_documents([
        VectorDocument(
            id="doc4",
            text="hello world",
            dense_vector=[0.1] * 384,
            repo="local",
            doc_type="doc",
            path="/tmp/hello.md"
        )
    ])

    # Suppose query embedding generates 1536d vector (mismatched)
    fake_vec = [0.5] * 1536
    with patch("app.services.embeddings.get_dense_embedding", return_value=fake_vec), \
         patch("app.services.vector_store.qdrant_store.get_dense_embedding", return_value=fake_vec), \
         patch("app.services.vector_store.chroma_store.get_dense_embedding", return_value=fake_vec), \
         patch("app.services.vector_store.pgvector_store.get_dense_embedding", return_value=fake_vec):
        with pytest.raises(ValueError) as exc_info:
            store.search("hello world")
        assert "Vector dimension mismatch" in str(exc_info.value)

        # Also test API endpoint returns 400 Bad Request
        res = client.post("/admin/api/search/test", json={"query": "hello world"})
        assert res.status_code == 400
        data = res.json()
        assert "Vector dimension mismatch" in data["error"]


def test_restart_clears_relational_metadata_on_collection_recreate(monkeypatch):
    """Verifies that on app restart, if ensure_collection detects a dimension mismatch and recreates the collection, relational metadata is cleared."""
    store = VectorStoreManager.get_vector_store()
    store.upsert_documents([
        VectorDocument(
            id="doc5",
            text="content 5",
            dense_vector=[0.1] * 384,
            repo="local",
            doc_type="doc",
            path="/tmp/file5.txt"
        )
    ])
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO indexed_files (filepath, repo, doc_type, language, mtime) VALUES (?, ?, ?, ?, ?)",
            ("/tmp/file5.txt", "local", "doc", "txt", 1.0)
        )
        conn.commit()

    # Change active dense model in memory to 1536d model, simulating app restart with updated config
    with patch("app.services.embeddings.get_dense_dim", return_value=1536), \
         patch("app.services.vector_store.qdrant_store.get_dense_dim", return_value=1536), \
         patch("app.services.vector_store.chroma_store.get_dense_dim", return_value=1536), \
         patch("app.services.vector_store.pgvector_store.get_dense_dim", return_value=1536):
        # Trigger ensure_collection
        ok = store.ensure_collection()
        assert ok is True

        # Verify relational metadata was cleared on recreate to keep vector points & relational state in sync
        with get_db_connection() as conn:
            cnt = conn.execute("SELECT count(*) FROM indexed_files").fetchone()[0]
            assert cnt == 0


def test_rollback_and_complete_rebuild(monkeypatch):
    """Tests model transition, rollback, and complete rebuild across local paths."""
    store = VectorStoreManager.get_vector_store()

    # Update to a new model with rebuild_index=True
    with patch("app.services.embeddings.get_dense_dim_for_config", return_value=1536), \
         patch("app.services.embeddings.get_dense_embeddings_batch", return_value=[[0.2] * 1536]), \
         patch("app.services.indexing.run_full_indexing") as mock_reindex:

        cfg1 = update_embedding_config(
            provider="api",
            dense_model="openai/text-embedding-3-small",
            rebuild_index=True
        )
        assert cfg1["dense_model"] == "openai/text-embedding-3-small"

        # Rollback to original local model with rebuild_index=True
        with patch("app.services.embeddings.get_dense_dim_for_config", return_value=384):
            cfg2 = update_embedding_config(
                provider="local",
                dense_model="BAAI/bge-small-en-v1.5",
                rebuild_index=True
            )
            assert cfg2["provider"] == "local"
            assert cfg2["dense_model"] == "BAAI/bge-small-en-v1.5"
