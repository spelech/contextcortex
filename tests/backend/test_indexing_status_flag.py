"""The "indexing is running" flag has one source of truth: indexing_lock.

These tests start a real run_full_indexing() on a thread with mocked work that
blocks, then check that every reader (stats, sync/reindex, poller) sees it.
"""
import sqlite3
import threading
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.services.indexing as idx_service
from app.api.routes import router
from app.services.indexing.state import indexing_lock

app = FastAPI()
app.include_router(router)
client = TestClient(app)


@pytest.fixture
def mock_db(tmp_path):
    db_file = str(tmp_path / "test_indexing_flag.db")
    conn = sqlite3.connect(db_file)
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

    def get_conn():
        c = sqlite3.connect(db_file)
        c.row_factory = sqlite3.Row
        return c

    with patch("app.services.database.get_db_connection", side_effect=get_conn):
        yield db_file


@pytest.fixture
def running_indexing(mock_db):
    """Start run_full_indexing() on a thread; its work blocks until the test ends."""
    started = threading.Event()
    release = threading.Event()
    result = {}

    def blocking_sync_local_paths(*_args, **_kwargs):
        started.set()
        assert release.wait(timeout=10), "test did not release the indexing run"

    with patch("app.services.indexing.state.ensure_collection", return_value=True), \
         patch("app.services.indexing.local_syncer.sync_local_paths", side_effect=blocking_sync_local_paths), \
         patch("app.services.indexing.git_syncer.set_metadata"), \
         patch("app.services.indexing.state.trigger_list_changed_notification"):
        worker = threading.Thread(
            target=lambda: result.setdefault("ok", idx_service.run_full_indexing()),
            daemon=True,
        )
        worker.start()
        assert started.wait(timeout=10), "indexing run did not start"
        try:
            yield result
        finally:
            release.set()
            worker.join(timeout=10)
    assert not worker.is_alive()


def _stats():
    store = MagicMock()
    store.health_check.return_value = (True, "OK")
    store.get_stats.return_value = {"points_count": 0}
    with patch("app.services.vector_store.get_vector_store", return_value=store), \
         patch("app.services.git_manager.check_github_rate_limit", return_value={"remaining": 5000, "limit": 5000}):
        res = client.get("/admin/api/stats")
    assert res.status_code == 200
    return res.json()


def test_is_indexing_is_a_function_backed_by_the_lock():
    from app.services.indexing import is_indexing as imported_by_value
    assert callable(imported_by_value)
    assert imported_by_value() is False
    with indexing_lock:
        assert imported_by_value() is True
        assert idx_service.is_indexing() is True
    assert imported_by_value() is False


def test_stats_reports_is_indexing_true_during_full_run(running_indexing):
    assert idx_service.is_indexing() is True
    assert _stats()["is_indexing"] is True


def test_is_indexing_false_again_when_run_completes(mock_db):
    with patch("app.services.indexing.state.ensure_collection", return_value=True), \
         patch("app.services.indexing.local_syncer.sync_local_paths"), \
         patch("app.services.indexing.git_syncer.set_metadata"), \
         patch("app.services.indexing.state.trigger_list_changed_notification"):
        assert idx_service.run_full_indexing() is True
    assert idx_service.is_indexing() is False
    assert _stats()["is_indexing"] is False


@pytest.mark.parametrize("endpoint", ["/admin/api/sync", "/admin/api/reindex"])
def test_sync_and_reindex_return_409_while_indexing(running_indexing, endpoint):
    with patch("app.services.indexing.run_full_indexing") as second_run:
        res = client.post(endpoint)
    assert res.status_code == 409
    assert res.json()["error"] == "Indexing in progress"
    second_run.assert_not_called()


def test_sync_dispatches_when_idle(mock_db):
    started = threading.Event()
    with patch("app.services.indexing.run_full_indexing", side_effect=started.set):
        res = client.post("/admin/api/sync")
        assert started.wait(timeout=10)
    assert res.status_code == 200
    assert res.json()["status"] == "success"


def test_poller_defers_while_full_run_holds_lock(running_indexing):
    from app.services.poller import check_all_auto_sync_repos
    with patch("app.services.poller.list_auto_sync_repos") as list_repos:
        assert check_all_auto_sync_repos() == (0, 0)
    list_repos.assert_not_called()
