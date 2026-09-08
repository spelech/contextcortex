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

def test_api_stats_reports_healthy_when_store_is_healthy(mock_db):
    mock_store = MagicMock()
    mock_store.health_check.return_value = (True, "OK")
    mock_store.get_stats.return_value = {"points_count": 42}

    with patch("app.services.vector_store.get_vector_store", return_value=mock_store), \
         patch("app.services.git_manager.check_github_rate_limit", return_value={"remaining": 5000, "limit": 5000}):
        res = client.get("/admin/api/stats")
        assert res.status_code == 200
        data = res.json()
        assert data["vector_db_status"] == "Healthy"
        assert data["points_count"] == 42
        mock_store.health_check.assert_called_once()

def test_api_stats_reports_unhealthy_when_store_fails(mock_db):
    mock_store = MagicMock()
    mock_store.health_check.return_value = (False, "Connection refused")
    mock_store.get_stats.return_value = {"points_count": 0}

    with patch("app.services.vector_store.get_vector_store", return_value=mock_store), \
         patch("app.services.git_manager.check_github_rate_limit", return_value={"remaining": 5000, "limit": 5000}):
        res = client.get("/admin/api/stats")
        assert res.status_code == 200
        data = res.json()
        assert data["vector_db_status"] == "Unhealthy"
