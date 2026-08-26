import os
import json
import sqlite3
import pytest
from unittest.mock import patch, MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.routes import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)

@pytest.fixture
def mock_db(tmp_path):
    db_file = str(tmp_path / "test_api.db")
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE system_metadata (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE indexed_files (id INTEGER PRIMARY KEY, filepath TEXT, repo TEXT, doc_type TEXT, language TEXT, hash TEXT, size INTEGER, last_modified REAL, added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE indexed_paths (id INTEGER PRIMARY KEY, path TEXT UNIQUE, type TEXT, recursive INTEGER, enabled INTEGER, category TEXT, repo TEXT, added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE git_repositories (id INTEGER PRIMARY KEY, name TEXT UNIQUE, url TEXT, branch TEXT, auth_token TEXT, provider TEXT DEFAULT 'github', auth_user TEXT, commit_sha TEXT, status TEXT DEFAULT 'pending', last_error TEXT, last_synced TEXT, enabled INTEGER DEFAULT 1, auto_sync INTEGER DEFAULT 1, webhook_secret TEXT, added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE git_host_credentials (id INTEGER PRIMARY KEY AUTOINCREMENT, host TEXT UNIQUE NOT NULL, provider TEXT NOT NULL, auth_user TEXT, auth_token TEXT NOT NULL, added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE ast_symbols (id INTEGER PRIMARY KEY, repo TEXT, filepath TEXT, kind TEXT, name TEXT, full_symbol TEXT, signature TEXT, start_line INTEGER, end_line INTEGER, language TEXT);
        CREATE TABLE file_summaries (filepath TEXT PRIMARY KEY, repo TEXT, title TEXT, folder TEXT, category TEXT, tags TEXT, headings TEXT, keywords TEXT, mtime REAL);
    """)
    conn.commit()
    conn.close()

    with patch("app.services.database.get_db_connection") as mock_conn:
        def get_conn():
            c = sqlite3.connect(db_file)
            c.row_factory = sqlite3.Row
            return c
        mock_conn.side_effect = get_conn
        yield db_file

def test_api_get_stats_with_keywords(mock_db):
    # Insert summaries with valid and corrupt keywords JSON
    with patch("app.services.database.get_db_connection") as mock_conn:
        conn = sqlite3.connect(mock_db)
        conn.execute("INSERT INTO file_summaries (filepath, keywords) VALUES ('/doc1.md', ?)", (json.dumps(["python", "fastapi", "rag"]),))
        conn.execute("INSERT INTO file_summaries (filepath, keywords) VALUES ('/doc2.md', ?)", ("corrupt_json_string{",))
        conn.commit()
        conn.close()

    mock_store = MagicMock()
    mock_store.get_stats.return_value = {"points_count": 120}

    with patch("app.services.vector_store.get_vector_store", return_value=mock_store), \
         patch("app.services.git_manager.check_github_rate_limit", return_value={"remaining": 4900, "limit": 5000}):
        res = client.get("/admin/api/stats")
        assert res.status_code == 200
        data = res.json()
        assert data["points_count"] == 120

        assert "python" in data["top_keywords"]
        assert "fastapi" in data["top_keywords"]
        assert data["rate_limit"]["remaining"] == 4900

def test_api_get_stats_error():
    with patch("app.services.database.get_db_connection", side_effect=RuntimeError("Database failure")):
        res = client.get("/admin/api/stats")
        assert res.status_code == 500
        assert "Database failure" in res.json()["error"]

def test_api_stats_field_names(mock_db):
    mock_store = MagicMock()
    mock_store.get_stats.return_value = {"points_count": 120}

    with patch("app.services.vector_store.get_vector_store", return_value=mock_store), \
         patch("app.services.git_manager.check_github_rate_limit", return_value={"remaining": 4900, "limit": 5000}):
        res = client.get("/admin/api/stats")
        assert res.status_code == 200
        data = res.json()
        assert "repos_count" in data
        assert "files_count" in data
        assert "symbols_count" in data
        assert "vector_store_provider" in data
        assert "vector_store_mode" in data
        assert "vector_store_collection" in data
        assert "git_repos" in data  # legacy backward compatibility

def test_api_repos_crud(mock_db):
    # Get initial repos
    res = client.get("/admin/api/repos")
    assert res.status_code == 200
    assert res.json() == []

    # Add repo missing fields
    res = client.post("/admin/api/repos", json={"name": "", "url": ""})
    assert res.status_code == 400

    # Add valid repo
    with patch("app.services.indexing.sync_single_git_repo"):
        res = client.post("/admin/api/repos", json={"name": "test-repo", "url": "https://github.com/example/test-repo.git", "branch": "main", "auth_token": "ghp_tok"})
        assert res.status_code == 200
        assert res.json()["status"] == "success"

        # Duplicate repo name
        res_dup = client.post("/admin/api/repos", json={"name": "test-repo", "url": "https://github.com/example/test-repo.git"})
        assert res_dup.status_code == 400

    # Get repos
    res = client.get("/admin/api/repos")
    assert res.status_code == 200
    repos = res.json()
    assert len(repos) == 1
    repo_id = repos[0]["id"]

    # Trigger sync
    with patch("app.services.indexing.sync_single_git_repo"):
        res_sync = client.post(f"/admin/api/repos/sync/{repo_id}")
        assert res_sync.status_code == 200
        res_sync_404 = client.post("/admin/api/repos/sync/999")
        assert res_sync_404.status_code == 404

    # Delete repo (with vector store error handled gracefully)
    with patch("app.services.vector_store.get_vector_store") as mock_get_store:
        mock_get_store.return_value.delete_by_repo.side_effect = Exception("Vector store connection down")
        res_del = client.delete(f"/admin/api/repos/{repo_id}")
        assert res_del.status_code == 200
        assert res_del.json()["status"] == "success"

        res_del_404 = client.delete("/admin/api/repos/999")
        assert res_del_404.status_code == 404


def test_api_repos_error_handlers():
    with patch("app.services.database.get_db_connection", side_effect=RuntimeError("DB error on repos")):
        # GET /admin/api/repos
        res = client.get("/admin/api/repos")
        assert res.status_code == 500
        assert "DB error on repos" in res.json()["error"]

        # POST /admin/api/repos
        res = client.post("/admin/api/repos", json={"name": "test", "url": "http://example.com"})
        assert res.status_code == 500

        # POST /admin/api/repos/sync/1
        res = client.post("/admin/api/repos/sync/1")
        assert res.status_code == 500

        # DELETE /admin/api/repos/1
        res = client.delete("/admin/api/repos/1")
        assert res.status_code == 500

def test_api_paths_crud(mock_db, tmp_path):
    sample_dir = tmp_path / "sample_workspace"
    sample_dir.mkdir()

    # Get initial paths
    res = client.get("/admin/api/paths")
    assert res.status_code == 200
    assert res.json() == []

    # Add invalid path
    res_inv = client.post("/admin/api/paths", json={"path": "/nonexistent/path/12345", "type": "directory"})
    assert res_inv.status_code == 400

    # Add valid path
    with patch("app.services.indexing.run_full_indexing"):
        res = client.post("/admin/api/paths", json={"path": str(sample_dir), "repo": "local-docs", "type": "directory", "recursive": True, "enabled": True})
        assert res.status_code == 200

        # Duplicate path
        res_dup = client.post("/admin/api/paths", json={"path": str(sample_dir), "repo": "local-docs"})
        assert res_dup.status_code == 400

    res = client.get("/admin/api/paths")
    paths = res.json()
    assert len(paths) == 1
    path_id = paths[0]["id"]

    # Delete path
    with patch("app.services.indexing.run_full_indexing"):
        res_del = client.delete(f"/admin/api/paths/{path_id}")
        assert res_del.status_code == 200
        res_del_404 = client.delete("/admin/api/paths/999")
        assert res_del_404.status_code == 404

def test_api_paths_error_handlers():
    with patch("app.services.database.get_db_connection", side_effect=RuntimeError("Paths DB error")):
        # GET /admin/api/paths
        res = client.get("/admin/api/paths")
        assert res.status_code == 500

        # POST /admin/api/paths
        with patch("os.path.exists", return_value=True):
            res = client.post("/admin/api/paths", json={"path": "/some/valid/path"})
            assert res.status_code == 500

        # DELETE /admin/api/paths/1
        res = client.delete("/admin/api/paths/1")
        assert res.status_code == 500

def test_api_settings_token(mock_db):
    with patch("app.services.git_manager.check_github_rate_limit", return_value={"remaining": 5000, "limit": 5000}):
        res = client.post("/admin/api/settings/token", json={"github_token": "ghp_test123456789"})
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"

def test_api_settings_token_error():
    with patch("app.services.database.set_metadata", side_effect=RuntimeError("Failed to store token")):
        res = client.post("/admin/api/settings/token", json={"github_token": "ghp_fail"})
        assert res.status_code == 500
        assert "Failed to store token" in res.json()["error"]

def test_api_search_test():
    # Empty query
    res = client.post("/admin/api/search/test", json={"query": "", "type": "code"})
    assert res.status_code == 400

    # Valid query
    mock_hit = MagicMock()
    mock_hit.score = 0.05
    mock_hit.payload = {"repo": "test", "rel_path": "main.py", "content": "print('hello')"}

    with patch("app.services.search.execute_hybrid_search", return_value=[mock_hit]):
        res = client.post("/admin/api/search/test", json={"query": "print hello", "type": "code", "repo": "test"})
        assert res.status_code == 200
        data = res.json()
        assert len(data["results"]) == 1
        assert data["results"][0]["score"] == 0.05

def test_api_search_test_error():
    with patch("app.services.search.execute_hybrid_search", side_effect=RuntimeError("Search index down")):
        res = client.post("/admin/api/search/test", json={"query": "print hello", "type": "code"})
        assert res.status_code == 500
        assert "Search index down" in res.json()["error"]

def test_api_reindex():
    with patch("app.services.indexing.is_indexing", return_value=False), \
          patch("app.services.indexing.run_full_indexing"):
        res = client.post("/admin/api/reindex")
        assert res.status_code == 200

    with patch("app.services.indexing.is_indexing", return_value=True):
        res = client.post("/admin/api/reindex")
        assert res.status_code == 409

def test_api_browse_dir(tmp_path):
    sub = tmp_path / "subdir"
    sub.mkdir()
    hidden_dir = tmp_path / ".hidden_dir"
    hidden_dir.mkdir()
    doc = tmp_path / "doc.txt"
    doc.write_text("hello")
    hidden_file = tmp_path / ".secret"
    hidden_file.write_text("secret")

    # Valid browse
    res = client.get(f"/admin/api/browse?path={tmp_path}")
    assert res.status_code == 200
    data = res.json()
    assert any(d["name"] == "subdir" for d in data["directories"])
    assert not any(d["name"] == ".hidden_dir" for d in data["directories"])
    assert any(f["name"] == "doc.txt" for f in data["files"])
    assert not any(f["name"] == ".secret" for f in data["files"])

    # Non-existent path fallback to "/"
    res_nonexistent = client.get("/admin/api/browse?path=/nonexistent_directory_abc123")
    assert res_nonexistent.status_code == 200
    assert res_nonexistent.json()["current_path"] == "/"

def test_api_browse_dir_error():
    with patch("os.scandir", side_effect=PermissionError("Directory read forbidden")):
        res = client.get("/admin/api/browse?path=/root")
        assert res.status_code == 500
        assert "Directory read forbidden" in res.json()["error"]

def test_api_logs_endpoints():
    res_del = client.delete("/admin/api/logs")
    assert res_del.status_code == 200
    assert res_del.json()["status"] == "success"

def test_api_logs_error_handlers():
    with patch("app.services.logger.get_diagnostic_logs", side_effect=RuntimeError("Logs read error")):
        res = client.get("/admin/api/logs")
        assert res.status_code == 500

    with patch("app.services.logger.clear_diagnostic_logs", side_effect=RuntimeError("Logs clear error")):
        res = client.delete("/admin/api/logs")
        assert res.status_code == 500

def test_api_embedding_settings(mock_db):
    # GET /admin/api/settings/embedding
    with patch("app.services.embeddings.get_embedding_config", return_value={
        "provider": "local",
        "dense_model": "BAAI/bge-small-en-v1.5",
        "sparse_model": "Qdrant/bm25",
        "threads": 2,
        "batch_size": 32,
        "system_cpus": 8,
        "system_memory_gb": 16.0,
        "litellm_url": "http://litellm:4000/v1"
    }):
        res = client.get("/admin/api/settings/embedding")
        assert res.status_code == 200
        data = res.json()
        assert data["threads"] == 2
        assert data["batch_size"] == 32
        assert data["system_cpus"] == 8

    # POST /admin/api/settings/embedding
    with patch("app.services.embeddings.update_embedding_config", return_value={
        "provider": "local",
        "dense_model": "BAAI/bge-small-en-v1.5",
        "sparse_model": "Qdrant/bm25",
        "threads": 4,
        "batch_size": 64,
        "system_cpus": 8,
        "system_memory_gb": 16.0,
        "litellm_url": "http://litellm:4000/v1"
    }):
        res = client.post("/admin/api/settings/embedding", json={
            "provider": "local",
            "threads": 4,
            "batch_size": 64
        })
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        assert data["config"]["threads"] == 4
        assert data["config"]["batch_size"] == 64

def test_api_embedding_settings_errors():
    with patch("app.services.embeddings.get_embedding_config", side_effect=RuntimeError("Embedding config error")):
        res = client.get("/admin/api/settings/embedding")
        assert res.status_code == 500
        assert "Embedding config error" in res.json()["error"]

    with patch("app.services.embeddings.update_embedding_config", side_effect=RuntimeError("Embedding update error")):
        res = client.post("/admin/api/settings/embedding", json={"provider": "local", "threads": 2})
        assert res.status_code == 500
        assert "Embedding update error" in res.json()["error"]

