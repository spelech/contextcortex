import os
import json
import sqlite3
import pytest
from unittest.mock import patch, MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import router
from app.services.vector_store import (
    VectorStoreManager,
    get_vector_store,
    get_vector_store_config,
)
from app.services.database import init_db, set_vector_store_db_config, get_vector_store_db_config
from app.mcp.tools import handle_index_status


app = FastAPI()
app.include_router(router)
client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_test_environment(tmp_path, monkeypatch):
    """Set up an isolated SQLite database and storage directory for each test."""
    db_file = str(tmp_path / "test_api_vs.db")
    storage_dir = str(tmp_path / "vector_storage")
    os.makedirs(storage_dir, exist_ok=True)

    monkeypatch.setenv("CACHE_DB_PATH", db_file)
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", db_file)
    monkeypatch.setattr("app.api.routes.CACHE_DB_PATH", db_file)
    monkeypatch.setenv("VECTOR_STORAGE_PATH", storage_dir)
    monkeypatch.setenv("DEFAULT_VECTOR_STORE_PROVIDER", "qdrant")
    monkeypatch.setenv("DEFAULT_VECTOR_STORE_MODE", "embedded")

    init_db(storage_dir)
    set_vector_store_db_config(
        provider="qdrant",
        mode="embedded",
        storage_path=storage_dir,
        url="",
        collection="test_api_col",
    )
    VectorStoreManager.reset_instance()

    yield {
        "db_file": db_file,
        "storage_dir": storage_dir,
    }

    VectorStoreManager.reset_instance()



# --- GET /admin/api/vector-store ---

def test_api_get_vector_store_success(setup_test_environment):
    """Test retrieving active vector store configuration and stats."""
    res = client.get("/admin/api/vector-store")
    assert res.status_code == 200
    data = res.json()
    assert "provider" in data
    assert data["provider"] in ("qdrant", "chroma")
    assert "mode" in data
    assert "collection" in data
    assert "healthy" in data
    assert "stats" in data
    assert "points_count" in data
    assert isinstance(data["points_count"], int)


def test_api_get_vector_store_error():
    """Test GET /admin/api/vector-store error handling."""
    with patch("app.services.vector_store.get_vector_store_config", side_effect=RuntimeError("Vector store config error")):
        res = client.get("/admin/api/vector-store")
        assert res.status_code == 500
        assert "Vector store config error" in res.json()["error"]


# --- POST /admin/api/vector-store/test ---

def test_api_test_vector_store_valid_embedded(setup_test_environment, tmp_path):
    """Test dry-run validation with valid embedded Qdrant configuration."""
    test_storage = str(tmp_path / "qdrant_test_dir")
    payload = {
        "provider": "qdrant",
        "mode": "embedded",
        "storage_path": test_storage,
        "collection": "test_collection",
    }
    res = client.post("/admin/api/vector-store/test", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "healthy" in data["message"].lower() or "success" in data["message"].lower()


def test_api_test_vector_store_valid_chroma(setup_test_environment, tmp_path):
    """Test dry-run validation with valid embedded Chroma configuration."""
    test_storage = str(tmp_path / "chroma_test_dir")
    payload = {
        "provider": "chroma",
        "mode": "embedded",
        "storage_path": test_storage,
        "collection": "test_chroma_col",
    }
    res = client.post("/admin/api/vector-store/test", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True


def test_api_test_vector_store_invalid_provider():
    """Test dry-run validation with unsupported provider."""
    payload = {
        "provider": "unsupported_backend",
        "mode": "embedded",
    }
    res = client.post("/admin/api/vector-store/test", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is False
    assert "unsupported" in data["message"].lower()


def test_api_test_vector_store_remote_missing_url():
    """Test dry-run validation with remote mode but missing URL."""
    payload = {
        "provider": "qdrant",
        "mode": "remote",
        "url": "",
    }
    res = client.post("/admin/api/vector-store/test", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is False
    assert "url" in data["message"].lower()


def test_api_test_vector_store_exception():
    """Test dry-run validation when unexpected exception occurs."""
    with patch("app.services.vector_store.test_vector_store_connection", side_effect=RuntimeError("Test crash")):
        payload = {"provider": "qdrant", "mode": "embedded"}
        res = client.post("/admin/api/vector-store/test", json=payload)
        assert res.status_code in (200, 500)
        data = res.json()
        assert data.get("success") is False or "error" in data


# --- POST /admin/api/vector-store/switch ---

def test_api_switch_vector_store_success(setup_test_environment, tmp_path):
    """Test switching vector store backend and triggering re-indexing."""
    chroma_dir = str(tmp_path / "chroma_switch_dir")
    payload = {
        "provider": "chroma",
        "mode": "embedded",
        "storage_path": chroma_dir,
        "collection": "switched_collection",
    }

    with patch("app.api.routes.run_full_indexing") as mock_reindex:
        res = client.post("/admin/api/vector-store/switch", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        assert "chroma" in data["message"].lower()

        # Check DB config was updated
        cfg = get_vector_store_db_config()
        assert cfg["provider"] == "chroma"
        assert cfg["collection"] == "switched_collection"


def test_api_switch_vector_store_invalid_provider():
    """Test switching to an unsupported provider returns 400."""
    payload = {
        "provider": "invalid_provider",
        "mode": "embedded",
    }
    res = client.post("/admin/api/vector-store/switch", json=payload)
    assert res.status_code == 400
    data = res.json()
    assert "error" in data or "message" in data


def test_api_switch_vector_store_exception():
    """Test handling of unexpected exception during switch."""
    with patch("app.services.vector_store.switch_vector_store", side_effect=RuntimeError("Switch crash")):
        payload = {"provider": "chroma", "mode": "embedded"}
        res = client.post("/admin/api/vector-store/switch", json=payload)
        assert res.status_code == 500


# --- Integration with GET /admin/api/stats and DELETE /admin/api/repos ---

def test_api_get_stats_uses_vector_store(setup_test_environment):
    """Test that GET /admin/api/stats queries the vector store adapter."""
    mock_store = MagicMock()
    mock_store.get_stats.return_value = {
        "backend": "qdrant",
        "points_count": 350,
        "mode": "embedded",
    }

    with patch("app.services.vector_store.get_vector_store", return_value=mock_store), \
         patch("app.services.git_manager.check_github_rate_limit", return_value={"remaining": 5000, "limit": 5000}):
        res = client.get("/admin/api/stats")
        assert res.status_code == 200
        data = res.json()
        assert data["points_count"] == 350
        mock_store.get_stats.assert_called_once()


def test_api_delete_repo_uses_vector_store(setup_test_environment):
    """Test that DELETE /admin/api/repos/{id} calls delete_by_repo on the vector store."""
    from app.services.database import get_db_connection
    with get_db_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO git_repositories (name, url, branch, provider) VALUES ('repo_to_del_unique', 'https://github.com/org/repo', 'main', 'github')"
        )
        conn.commit()
        repo_id = conn.execute("SELECT id FROM git_repositories WHERE name = 'repo_to_del_unique'").fetchone()[0]

    mock_store = MagicMock()
    with patch("app.services.vector_store.get_vector_store", return_value=mock_store):
        res = client.delete(f"/admin/api/repos/{repo_id}")
        assert res.status_code == 200
        mock_store.delete_by_repo.assert_called_once_with("repo_to_del_unique")



# --- MCP handle_index_status() ---

@pytest.mark.asyncio
async def test_mcp_handle_index_status_details(setup_test_environment):
    """Test that handle_index_status includes provider, mode, location, collection, and counts."""
    with patch("app.services.git_manager.check_github_rate_limit", return_value={"remaining": 5000, "limit": 5000}):
        res = await handle_index_status()
        assert "Vector Store Provider: QDRANT" in res
        assert "Storage Mode:" in res
        assert "Collection:" in res
        assert "Total Vectors:" in res
        assert "Embedding Provider:" in res


@pytest.mark.asyncio
async def test_mcp_handle_index_status_chroma(setup_test_environment, tmp_path):
    """Test handle_index_status after switching to Chroma."""
    chroma_dir = str(tmp_path / "chroma_status_dir")
    set_vector_store_db_config(
        provider="chroma",
        mode="embedded",
        storage_path=chroma_dir,
        collection="chroma_notes",
    )
    VectorStoreManager.reset_instance()

    with patch("app.services.git_manager.check_github_rate_limit", return_value={"remaining": 5000, "limit": 5000}):
        res = await handle_index_status()
        assert "Vector Store Provider: CHROMA" in res
        assert "Collection: chroma_notes" in res
