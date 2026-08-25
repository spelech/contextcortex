import os
import sqlite3
import pytest
from unittest.mock import MagicMock, patch

from app.services.database import (
    init_db,
    get_metadata,
    set_metadata,
    get_default_vector_storage_path,
    get_vector_store_db_config,
    set_vector_store_db_config,
)
from app.services.vector_store.base import VectorStore
from app.services.vector_store.qdrant_store import QdrantVectorStore
from app.services.vector_store.chroma_store import ChromaVectorStore
from app.services.vector_store.manager import (
    VectorStoreManager,
    get_vector_store,
    get_vector_store_config,
    switch_vector_store,
)


@pytest.fixture(autouse=True)
def isolated_db_and_manager(tmp_path, monkeypatch):
    """Isolate DB path and VectorStoreManager singleton per test."""
    test_db_path = str(tmp_path / "test_index_cache.db")
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", test_db_path)
    
    # Reset manager singleton instance
    VectorStoreManager.reset_instance()
    yield
    VectorStoreManager.reset_instance()


class TestDBVectorStoreSeeding:
    """Tests for SQLite system_metadata seeding of vector store settings."""

    def test_seed_defaults_when_env_empty(self, monkeypatch, tmp_path):
        monkeypatch.delenv("VECTOR_STORE", raising=False)
        monkeypatch.delenv("VECTOR_STORE_PROVIDER", raising=False)
        monkeypatch.delenv("VECTOR_STORE_MODE", raising=False)
        monkeypatch.delenv("VECTOR_STORE_STORAGE_PATH", raising=False)
        monkeypatch.delenv("VECTOR_STORE_URL", raising=False)
        monkeypatch.delenv("QDRANT_URL", raising=False)
        monkeypatch.delenv("CHROMA_URL", raising=False)
        monkeypatch.delenv("COLLECTION_NAME", raising=False)
        monkeypatch.delenv("VECTOR_STORE_COLLECTION", raising=False)

        init_db()

        config = get_vector_store_db_config()
        assert config["provider"] == "qdrant"
        assert config["mode"] == "embedded"
        assert "vector_storage" in config["storage_path"]
        assert config["url"] == ""
        assert config["collection"] == "knowledge_rag_v1"

    def test_seed_from_environment_variables(self, monkeypatch, tmp_path):
        custom_storage = str(tmp_path / "custom_vectors")
        monkeypatch.setenv("VECTOR_STORE", "chroma")
        monkeypatch.setenv("VECTOR_STORE_MODE", "remote")
        monkeypatch.setenv("VECTOR_STORE_STORAGE_PATH", custom_storage)
        monkeypatch.setenv("CHROMA_URL", "http://chroma-host:8000")
        monkeypatch.setenv("COLLECTION_NAME", "my_custom_coll")

        init_db()

        config = get_vector_store_db_config()
        assert config["provider"] == "chroma"
        assert config["mode"] == "remote"
        assert config["storage_path"] == custom_storage
        assert config["url"] == "http://chroma-host:8000"
        assert config["collection"] == "my_custom_coll"

    def test_seed_with_alt_env_vars(self, monkeypatch, tmp_path):
        monkeypatch.setenv("VECTOR_STORE_PROVIDER", "qdrant")
        monkeypatch.setenv("VECTOR_STORE_COLLECTION", "alt_coll")
        monkeypatch.setenv("VECTOR_STORE_URL", "http://alt-url:6333")
        monkeypatch.setenv("VECTOR_STORE_MODE", "remote")

        init_db()

        config = get_vector_store_db_config()
        assert config["provider"] == "qdrant"
        assert config["mode"] == "remote"
        assert config["url"] == "http://alt-url:6333"
        assert config["collection"] == "alt_coll"

    def test_init_db_does_not_overwrite_existing_db_metadata(self, monkeypatch):
        init_db()
        set_vector_store_db_config(
            provider="chroma",
            mode="embedded",
            storage_path="/custom/path",
            url="",
            collection="persisted_coll"
        )

        # Call init_db again with conflicting env vars
        monkeypatch.setenv("VECTOR_STORE", "qdrant")
        monkeypatch.setenv("COLLECTION_NAME", "env_coll")
        init_db()

        # Existing DB metadata must be preserved
        config = get_vector_store_db_config()
        assert config["provider"] == "chroma"
        assert config["collection"] == "persisted_coll"
        assert config["storage_path"] == "/custom/path"

    def test_get_default_vector_storage_path_env_override(self, monkeypatch):
        monkeypatch.setenv("VECTOR_STORE_STORAGE_PATH", "/custom/vector/store/path")
        path = get_default_vector_storage_path()
        assert path == "/custom/vector/store/path"


class TestVectorStoreManagerRetrieval:
    """Tests for get_vector_store singleton instantiation."""

    def test_get_vector_store_qdrant_embedded(self, monkeypatch, tmp_path):
        storage_path = str(tmp_path / "qdrant_data")
        monkeypatch.delenv("QDRANT_URL", raising=False)
        init_db()
        set_vector_store_db_config(
            provider="qdrant",
            mode="embedded",
            storage_path=storage_path,
            url="",
            collection="test_qdrant_mgr"
        )

        store = get_vector_store()
        assert isinstance(store, QdrantVectorStore)
        assert isinstance(store, VectorStore)
        assert store.mode in ("embedded", "memory")
        assert store.collection_name == "test_qdrant_mgr"

        # Singleton check: repeated calls return identical instance
        store2 = get_vector_store()
        assert store is store2

    def test_get_vector_store_chroma_embedded(self, tmp_path):
        storage_path = str(tmp_path / "chroma_data")
        init_db()
        set_vector_store_db_config(
            provider="chroma",
            mode="embedded",
            storage_path=storage_path,
            url="",
            collection="test_chroma_mgr"
        )

        store = get_vector_store()
        assert isinstance(store, ChromaVectorStore)
        assert isinstance(store, VectorStore)
        assert store.mode in ("persistent", "memory")
        assert store.collection_name == "test_chroma_mgr"

    def test_get_vector_store_qdrant_remote(self):
        init_db()
        set_vector_store_db_config(
            provider="qdrant",
            mode="remote",
            storage_path="",
            url="http://remote-qdrant:6333",
            collection="test_qdrant_remote"
        )

        mock_client = MagicMock()
        mock_client.get_collections.return_value = MagicMock(collections=[])
        mock_client.collection_exists.return_value = True

        with patch("app.services.vector_store.qdrant_store.QdrantClient", return_value=mock_client):
            store = get_vector_store(force_reload=True)
            assert isinstance(store, QdrantVectorStore)
            assert store.mode == "remote"
            assert store.location == "http://remote-qdrant:6333"

    def test_get_vector_store_chroma_remote(self):
        init_db()
        set_vector_store_db_config(
            provider="chroma",
            mode="remote",
            storage_path="",
            url="http://remote-chroma:8000",
            collection="test_chroma_remote"
        )

        mock_client = MagicMock()
        mock_client.heartbeat.return_value = 123456
        mock_coll = MagicMock()
        mock_coll.name = "test_chroma_remote"
        mock_client.get_or_create_collection.return_value = mock_coll

        with patch("app.services.vector_store.chroma_store.chromadb.HttpClient", return_value=mock_client):
            store = get_vector_store(force_reload=True)
            assert isinstance(store, ChromaVectorStore)
            assert store.mode == "remote"
            assert "remote-chroma" in store.location

    def test_get_vector_store_force_reload(self, tmp_path):
        storage_path = str(tmp_path / "qdrant_data")
        init_db()
        set_vector_store_db_config(
            provider="qdrant",
            mode="embedded",
            storage_path=storage_path,
            url="",
            collection="test_reload_coll"
        )

        store1 = get_vector_store()
        store2 = get_vector_store(force_reload=True)
        assert store1 is not store2
        assert isinstance(store2, QdrantVectorStore)


class TestVectorStoreManagerSwitching:
    """Tests for dynamic switching between vector database providers and modes."""

    def test_switch_from_qdrant_to_chroma(self, tmp_path):
        qdrant_path = str(tmp_path / "qdrant_data")
        chroma_path = str(tmp_path / "chroma_data")
        init_db()
        set_vector_store_db_config(
            provider="qdrant",
            mode="embedded",
            storage_path=qdrant_path,
            url="",
            collection="initial_coll"
        )

        initial_store = get_vector_store()
        assert isinstance(initial_store, QdrantVectorStore)

        reindex_called = False
        def mock_reindex():
            nonlocal reindex_called
            reindex_called = True

        # Also test global registered callback
        global_reindex_called = False
        def global_mock_reindex():
            nonlocal global_reindex_called
            global_reindex_called = True

        VectorStoreManager.register_reindex_callback(global_mock_reindex)

        success, msg = switch_vector_store(
            provider="chroma",
            mode="embedded",
            storage_path=chroma_path,
            url="",
            collection="switched_chroma_coll",
            reindex_callback=mock_reindex
        )
        assert success is True
        assert "chroma" in msg.lower()
        assert reindex_called is True
        assert global_reindex_called is True

        # Unregister callback and switch again
        VectorStoreManager.unregister_reindex_callback(global_mock_reindex)
        global_reindex_called = False
        switch_vector_store(
            provider="chroma",
            mode="embedded",
            storage_path=chroma_path,
            url="",
            collection="switched_chroma_coll_2"
        )
        assert global_reindex_called is False

        # Verify DB metadata was updated
        config = get_vector_store_db_config()
        assert config["provider"] == "chroma"
        assert config["mode"] == "embedded"
        assert config["storage_path"] == chroma_path
        assert config["collection"] == "switched_chroma_coll_2"

        # Verify new store is ChromaVectorStore
        new_store = get_vector_store()
        assert isinstance(new_store, ChromaVectorStore)
        assert new_store.collection_name == "switched_chroma_coll_2"

    def test_switch_validation_invalid_provider(self):
        init_db()
        success, msg = switch_vector_store(
            provider="unsupported_backend",
            mode="embedded"
        )
        assert success is False
        assert "unsupported" in msg.lower()

    def test_switch_validation_invalid_mode(self):
        init_db()
        success, msg = switch_vector_store(
            provider="qdrant",
            mode="invalid_mode"
        )
        assert success is False
        assert "unsupported" in msg.lower()

    def test_switch_validation_remote_without_url(self):
        init_db()
        success, msg = switch_vector_store(
            provider="qdrant",
            mode="remote",
            url=""
        )
        assert success is False
        assert "url" in msg.lower()

    def test_switch_failure_when_ensure_collection_fails(self, monkeypatch):
        init_db()
        with patch.object(QdrantVectorStore, "ensure_collection", return_value=False):
            success, msg = switch_vector_store(
                provider="qdrant",
                mode="embedded",
                collection="fail_coll"
            )
            assert success is False
            assert "failed to ensure collection" in msg.lower()


class TestVectorStoreManagerConfigAndHealth:
    """Tests for get_vector_store_config and health aggregation."""

    def test_get_vector_store_config(self, tmp_path):
        storage_path = str(tmp_path / "qdrant_data")
        init_db()
        set_vector_store_db_config(
            provider="qdrant",
            mode="embedded",
            storage_path=storage_path,
            url="",
            collection="health_coll"
        )

        cfg = get_vector_store_config()
        assert cfg["provider"] == "qdrant"
        assert cfg["mode"] == "embedded"
        assert cfg["storage_path"] == storage_path
        assert cfg["collection"] == "health_coll"
        assert cfg["healthy"] is True
        assert isinstance(cfg["stats"], dict)
        assert cfg["stats"]["backend"] == "qdrant"

    def test_get_vector_store_config_on_error(self):
        init_db()
        set_vector_store_db_config(
            provider="qdrant",
            mode="embedded",
            storage_path="/nonexistent/readonly/path",
            url="",
            collection="error_coll"
        )

        with patch.object(VectorStoreManager, "get_vector_store", side_effect=RuntimeError("Store init failed")):
            cfg = get_vector_store_config()
            assert cfg["healthy"] is False
            assert "error" in cfg["health_message"].lower()
            assert "error" in cfg["stats"]

    def test_test_connection_active_embedded(self, tmp_path):
        """Verify test_connection succeeds on active embedded Qdrant store without file lock conflict."""
        storage_path = str(tmp_path / "qdrant_active_dir")
        init_db()
        set_vector_store_db_config(
            provider="qdrant",
            mode="embedded",
            storage_path=storage_path,
            url="",
            collection="test_active_coll"
        )
        store = get_vector_store(force_reload=True)
        assert store.mode == "embedded"

        # Testing the same active path must succeed without RuntimeError / AlreadyLocked
        ok, msg = VectorStoreManager.test_connection(
            provider="qdrant",
            mode="embedded",
            storage_path=storage_path,
            collection="test_active_coll"
        )
        assert ok is True
        assert "healthy" in msg.lower()

    def test_switch_same_embedded_directory(self, tmp_path):
        """Verify switch_vector_store succeeds when switching collection on the same embedded Qdrant directory."""
        storage_path = str(tmp_path / "qdrant_active_dir2")
        init_db()
        set_vector_store_db_config(
            provider="qdrant",
            mode="embedded",
            storage_path=storage_path,
            url="",
            collection="coll_v1"
        )
        store = get_vector_store(force_reload=True)
        assert store.collection_name == "coll_v1"

        # Switch collection on the same storage path
        ok, msg = switch_vector_store(
            provider="qdrant",
            mode="embedded",
            storage_path=storage_path,
            collection="coll_v2"
        )
        assert ok is True
        assert "successfully switched" in msg.lower()
        new_store = get_vector_store()
        assert new_store.collection_name == "coll_v2"

