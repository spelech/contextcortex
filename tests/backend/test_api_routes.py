import os
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
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE indexed_files (id INTEGER PRIMARY KEY, path TEXT, repo TEXT, hash TEXT, size INTEGER, last_modified REAL, indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE indexed_paths (id INTEGER PRIMARY KEY, path TEXT UNIQUE, type TEXT, recursive INTEGER, enabled INTEGER, category TEXT, repo TEXT, added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE git_repositories (id INTEGER PRIMARY KEY, name TEXT UNIQUE, url TEXT, branch TEXT, auth_token TEXT, commit_sha TEXT, status TEXT DEFAULT 'pending', last_error TEXT, last_synced TEXT, enabled INTEGER DEFAULT 1, added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE ast_symbols (id INTEGER PRIMARY KEY, repo TEXT, rel_path TEXT, symbol_type TEXT, name TEXT, signature TEXT, start_line INTEGER, end_line INTEGER);
        CREATE TABLE file_summaries (id INTEGER PRIMARY KEY, repo TEXT, rel_path TEXT, category TEXT, summary TEXT, keywords TEXT, indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
    """)
    conn.commit()
    conn.close()

    with patch("app.api.routes.get_db_connection") as mock_conn:
        def get_conn():
            c = sqlite3.connect(db_file)
            c.row_factory = sqlite3.Row
            return c
        mock_conn.side_effect = get_conn
        yield db_file

def test_api_get_stats(mock_db):
    with patch("app.api.routes.qdrant") as mock_qdrant, \
         patch("app.api.routes.check_github_rate_limit", return_value={"remaining": 4900, "limit": 5000}):
        mock_qdrant.collection_exists.return_value = True
        mock_info = MagicMock()
        mock_info.points_count = 120
        mock_qdrant.get_collection.return_value = mock_info

        res = client.get("/admin/api/stats")
        assert res.status_code == 200
        data = res.json()
        assert data["points_count"] == 120
        assert data["rate_limit"]["remaining"] == 4900

def test_api_repos_crud(mock_db):
    # Get initial repos
    res = client.get("/admin/api/repos")
    assert res.status_code == 200
    assert res.json() == []

    # Add repo missing fields
    res = client.post("/admin/api/repos", json={"name": "", "url": ""})
    assert res.status_code == 400

    # Add valid repo
    with patch("app.api.routes.sync_single_git_repo"):
        res = client.post("/admin/api/repos", json={"name": "test-repo", "url": "https://github.com/example/test-repo.git", "branch": "main"})
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
    with patch("app.api.routes.sync_single_git_repo"):
        res_sync = client.post(f"/admin/api/repos/sync/{repo_id}")
        assert res_sync.status_code == 200
        res_sync_404 = client.post("/admin/api/repos/sync/999")
        assert res_sync_404.status_code == 404

    # Delete repo
    with patch("app.api.routes.qdrant"):
        res_del = client.delete(f"/admin/api/repos/{repo_id}")
        assert res_del.status_code == 200
        res_del_404 = client.delete("/admin/api/repos/999")
        assert res_del_404.status_code == 404

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
    with patch("app.api.routes.run_full_indexing"):
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
    with patch("app.api.routes.run_full_indexing"):
        res_del = client.delete(f"/admin/api/paths/{path_id}")
        assert res_del.status_code == 200
        res_del_404 = client.delete("/admin/api/paths/999")
        assert res_del_404.status_code == 404

def test_api_settings_token(mock_db):
    with patch("app.api.routes.check_github_rate_limit", return_value={"remaining": 5000, "limit": 5000}):
        res = client.post("/admin/api/settings/token", json={"github_token": "ghp_test123456789"})
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"

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

def test_api_reindex():
    with patch("app.api.routes.is_indexing", False), \
         patch("app.api.routes.run_full_indexing"):
        res = client.post("/admin/api/reindex")
        assert res.status_code == 200

    with patch("app.api.routes.is_indexing", True):
        res = client.post("/admin/api/reindex")
        assert res.status_code == 409

def test_api_browse_dir(tmp_path):
    sub = tmp_path / "subdir"
    sub.mkdir()
    doc = tmp_path / "doc.txt"
    doc.write_text("hello")

    res = client.get(f"/admin/api/browse?path={tmp_path}")
    assert res.status_code == 200
    data = res.json()
    assert any(d["name"] == "subdir" for d in data["directories"])
    assert any(f["name"] == "doc.txt" for f in data["files"])
