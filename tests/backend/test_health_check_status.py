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
        CREATE TABLE git_repositories (id INTEGER PRIMARY KEY, name TEXT UNIQUE, url TEXT, branch TEXT, auth_token TEXT, provider TEXT DEFAULT 'github', auth_user TEXT, commit_sha TEXT, status TEXT DEFAULT 'pending', last_error TEXT, last_synced TEXT, enabled INTEGER DEFAULT 1, auto_sync INTEGER DEFAULT 1, keep_shallow INTEGER DEFAULT 0, webhook_secret TEXT, added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE git_host_credentials (id INTEGER PRIMARY KEY AUTOINCREMENT, host TEXT UNIQUE NOT NULL, provider TEXT NOT NULL, auth_user TEXT, auth_token TEXT NOT NULL, added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE ast_symbols (id INTEGER PRIMARY KEY, repo TEXT, filepath TEXT, kind TEXT, name TEXT, full_symbol TEXT, signature TEXT, start_line INTEGER, end_line INTEGER, language TEXT);
        CREATE TABLE ast_relationships (id INTEGER PRIMARY KEY, repo TEXT, source_symbol_id INTEGER, source_filepath TEXT, source_symbol TEXT, target_symbol TEXT, relationship_type TEXT, line_number INTEGER);
        CREATE TABLE api_routes (id INTEGER PRIMARY KEY, repo TEXT, filepath TEXT, http_method TEXT, route_path TEXT, handler_function TEXT, line_number INTEGER);
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

def test_api_stats_reports_healthy_with_real_embedded_store(tmp_path):
    """Verify /admin/api/stats health check against a real embedded Qdrant vector store without mocks."""
    from app.services.database import set_vector_store_db_config
    from app.services.vector_store import VectorStoreManager

    qdrant_dir = str(tmp_path / "real_health_qdrant")
    set_vector_store_db_config(
        provider="qdrant",
        mode="embedded",
        storage_path=qdrant_dir,
        url="",
        collection="test_health_check",
    )
    VectorStoreManager.reset_instance()

    with patch("app.services.git_manager.check_github_rate_limit", return_value={"remaining": 5000, "limit": 5000}):
        res = client.get("/admin/api/stats")
        assert res.status_code == 200
        data = res.json()
        assert data["vector_db_status"] == "Healthy"
        assert data["vector_store_provider"] == "qdrant"
        assert data["vector_store_mode"] == "embedded"


def test_api_stats_healthy_empty_db_returns_zeros(mock_db):
    """Verify that a healthy, empty database returns status 200 with legitimate zero counts."""
    mock_store = MagicMock()
    mock_store.health_check.return_value = (True, "OK")
    mock_store.get_stats.return_value = {"points_count": 0}

    with patch("app.services.vector_store.get_vector_store", return_value=mock_store), \
         patch("app.services.git_manager.check_github_rate_limit", return_value={"remaining": 5000, "limit": 5000}):
        res = client.get("/admin/api/stats")
        assert res.status_code == 200
        data = res.json()
        assert data["repos_count"] == 0
        assert data["files_count"] == 0
        assert data["symbols_count"] == 0
        assert data["points_count"] == 0


def test_api_stats_missing_table_returns_error(tmp_path):
    """Verify that missing table in relational database produces 500 error rather than success-shaped zero counts."""
    incomplete_db = str(tmp_path / "incomplete.db")
    conn = sqlite3.connect(incomplete_db)
    conn.execute("CREATE TABLE system_metadata (key TEXT PRIMARY KEY, value TEXT)")
    conn.commit()
    conn.close()

    mock_store = MagicMock()
    mock_store.health_check.return_value = (True, "OK")
    mock_store.get_stats.return_value = {"points_count": 0}

    with patch("app.services.database.get_db_connection", side_effect=lambda: sqlite3.connect(incomplete_db)), \
         patch("app.services.vector_store.get_vector_store", return_value=mock_store), \
         patch("app.services.git_manager.check_github_rate_limit", return_value={"remaining": 5000, "limit": 5000}):
        res = client.get("/admin/api/stats")
        assert res.status_code == 500
        assert "error" in res.json()


def test_api_stats_postgres_reproduction_surfaces_metadata_failure(monkeypatch):
    """Reproduce #45 PostgreSQL scenario: metadata failure surfaces 500 error instead of 200 zero counts."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/testdb")

    mock_store = MagicMock()
    mock_store.health_check.return_value = (True, "OK")
    mock_store.get_stats.return_value = {"points_count": 100}

    mock_engine = MagicMock()
    mock_conn = MagicMock()
    # Execute raises relational error (e.g., table does not exist)
    mock_conn.execute.side_effect = RuntimeError("UndefinedTable: relation 'git_repositories' does not exist")
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    with patch("app.services.database.engine.get_db_engine", return_value=mock_engine), \
         patch("app.services.vector_store.get_vector_store", return_value=mock_store), \
         patch("app.services.git_manager.check_github_rate_limit", return_value={"remaining": 5000, "limit": 5000}):
        res = client.get("/admin/api/stats")
        assert res.status_code == 500
        assert "error" in res.json()


def test_main_app_favicon_and_root_redirect():
    """Verify root app redirect, favicon routes, and static asset handling."""
    from main import app as main_app
    main_client = TestClient(main_app)

    res_root = main_client.get("/", follow_redirects=False)
    assert res_root.status_code == 307
    assert res_root.headers["location"] == "/admin/"

    res_favicon = main_client.get("/favicon.svg")
    assert res_favicon.status_code == 200
    assert "image/svg+xml" in res_favicon.headers.get("content-type", "")

    res_ico = main_client.get("/favicon.ico")
    assert res_ico.status_code == 200

