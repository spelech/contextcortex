import time
import pytest
from unittest.mock import MagicMock, patch
from app.services.db import init_db, get_db_connection, set_auto_sync_interval

def test_check_all_auto_sync_repos_triggers_sync(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_poller1.db")
    monkeypatch.setattr("app.services.db.CACHE_DB_PATH", test_db)
    init_db()
    from app.services.poller import check_all_auto_sync_repos

    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO git_repositories (name, url, branch, commit_sha, auto_sync) VALUES (?, ?, ?, ?, ?)",
            ("poll-test-repo", "https://github.com/example/poll-repo.git", "main", "sha-111", 1)
        )
        conn.commit()

    synced_ids = []
    def mock_get_remote_sha(url, branch, **kwargs):
        return "sha-222"  # Changed SHA

    def mock_sync_repo(repo_id):
        synced_ids.append(repo_id)

    monkeypatch.setattr("app.services.poller.get_remote_head_sha", mock_get_remote_sha)
    monkeypatch.setattr("app.services.poller.sync_single_git_repo", mock_sync_repo)
    monkeypatch.setattr("app.services.poller.is_indexing", False)

    checked, updated = check_all_auto_sync_repos()
    assert checked == 1
    assert updated == 1
    assert len(synced_ids) == 1

def test_check_all_auto_sync_repos_skips_up_to_date(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_poller2.db")
    monkeypatch.setattr("app.services.db.CACHE_DB_PATH", test_db)
    init_db()
    from app.services.poller import check_all_auto_sync_repos

    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO git_repositories (name, url, branch, commit_sha, auto_sync) VALUES (?, ?, ?, ?, ?)",
            ("up-to-date-repo", "https://github.com/example/up-to-date.git", "main", "sha-current", 1)
        )
        conn.commit()

    synced_ids = []
    def mock_get_remote_sha(url, branch, **kwargs):
        return "sha-current"  # Same SHA

    def mock_sync_repo(repo_id):
        synced_ids.append(repo_id)

    monkeypatch.setattr("app.services.poller.get_remote_head_sha", mock_get_remote_sha)
    monkeypatch.setattr("app.services.poller.sync_single_git_repo", mock_sync_repo)
    monkeypatch.setattr("app.services.poller.is_indexing", False)

    checked, updated = check_all_auto_sync_repos()
    assert checked == 1
    assert updated == 0
    assert len(synced_ids) == 0

def test_check_all_auto_sync_repos_deferred_when_indexing(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_poller3.db")
    monkeypatch.setattr("app.services.db.CACHE_DB_PATH", test_db)
    init_db()
    from app.services.poller import check_all_auto_sync_repos

    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO git_repositories (name, url, branch, commit_sha, auto_sync) VALUES (?, ?, ?, ?, ?)",
            ("repo1", "https://github.com/example/repo1.git", "main", "sha-1", 1)
        )
        conn.commit()

    monkeypatch.setattr("app.services.poller.is_indexing", True)
    checked, updated = check_all_auto_sync_repos()
    assert checked == 0
    assert updated == 0

def test_check_all_auto_sync_repos_no_repos(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_poller4.db")
    monkeypatch.setattr("app.services.db.CACHE_DB_PATH", test_db)
    init_db()
    from app.services.poller import check_all_auto_sync_repos

    monkeypatch.setattr("app.services.poller.is_indexing", False)
    checked, updated = check_all_auto_sync_repos()
    assert checked == 0
    assert updated == 0

def test_check_all_auto_sync_repos_handles_error(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_poller5.db")
    monkeypatch.setattr("app.services.db.CACHE_DB_PATH", test_db)
    init_db()
    from app.services.poller import check_all_auto_sync_repos

    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO git_repositories (name, url, branch, commit_sha, auto_sync) VALUES (?, ?, ?, ?, ?)",
            ("error-repo", "https://github.com/example/error-repo.git", "main", "sha-1", 1)
        )
        conn.commit()

    def mock_get_remote_sha_error(*args, **kwargs):
        raise RuntimeError("Git network failure")

    monkeypatch.setattr("app.services.poller.get_remote_head_sha", mock_get_remote_sha_error)
    monkeypatch.setattr("app.services.poller.is_indexing", False)

    checked, updated = check_all_auto_sync_repos()
    assert checked == 0
    assert updated == 0

def test_trigger_poller_check_now(monkeypatch):
    from app.services.poller import trigger_poller_check_now
    mock_check = MagicMock(return_value=(2, 1))
    monkeypatch.setattr("app.services.poller.check_all_auto_sync_repos", mock_check)

    res = trigger_poller_check_now()
    assert res == (2, 1)
    mock_check.assert_called_once()

def test_poller_daemon_lifecycle():
    from app.services.poller import start_poller_daemon, stop_poller_daemon, _poller_stop_event
    stop_poller_daemon()
    assert _poller_stop_event.is_set()

    with patch("threading.Thread") as mock_thread_cls:
        mock_instance = MagicMock()
        mock_instance.is_alive.return_value = False
        mock_thread_cls.return_value = mock_instance

        start_poller_daemon()
        assert not _poller_stop_event.is_set()
        mock_thread_cls.assert_called_once()
        mock_instance.start.assert_called_once()

        # Calling start again when alive should be a no-op
        mock_instance.is_alive.return_value = True
        start_poller_daemon()
        assert mock_thread_cls.call_count == 1

    stop_poller_daemon()
    assert _poller_stop_event.is_set()

def test_poller_worker_cycle(monkeypatch):
    from app.services.poller import _poller_worker, _poller_stop_event, stop_poller_daemon
    calls = []
    def mock_check():
        calls.append(1)
        stop_poller_daemon()
        return (1, 1)

    monkeypatch.setattr("app.services.poller.check_all_auto_sync_repos", mock_check)
    monkeypatch.setattr("app.services.poller.get_auto_sync_interval", lambda: 1)
    monkeypatch.setattr("time.sleep", lambda s: None)

    _poller_stop_event.clear()
    _poller_worker()
    assert len(calls) == 1

def test_poller_worker_disabled_interval(monkeypatch):
    from app.services.poller import _poller_worker, _poller_stop_event, stop_poller_daemon
    calls = []
    def mock_check():
        calls.append(1)
        return (1, 1)

    monkeypatch.setattr("app.services.poller.check_all_auto_sync_repos", mock_check)
    monkeypatch.setattr("app.services.poller.get_auto_sync_interval", lambda: 0)

    def fake_sleep(s):
        stop_poller_daemon()

    monkeypatch.setattr("time.sleep", fake_sleep)

    _poller_stop_event.clear()
    _poller_worker()
    assert len(calls) == 0
