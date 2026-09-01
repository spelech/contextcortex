import os
import pytest
from unittest.mock import patch, MagicMock
from app.models.schemas import CloneResult
from app.services.indexing.git_progress import progress_tracker, GitProgressTracker
from app.services.indexing.git_syncer import sync_single_git_repo


@pytest.fixture(autouse=True)
def reset_progress_tracker():
    tracker = GitProgressTracker()
    with tracker._lock:
        tracker.jobs.clear()
    yield
    with tracker._lock:
        tracker.jobs.clear()


@patch("app.services.database.get_db_connection")
@patch("app.services.git_manager.get_remote_head_sha")
def test_git_syncer_reports_stages_up_to_date(mock_sha, mock_db):
    mock_conn = MagicMock()
    mock_db.return_value.__enter__.return_value = mock_conn
    mock_conn.execute.return_value.fetchone.return_value = {
        "id": 101, "name": "up-to-date-repo", "url": "https://github.com/test/repo.git",
        "branch": "main", "commit_sha": "abc123456", "auth_token": None, "auth_user": None, "provider": "github"
    }
    mock_sha.return_value = "abc123456"

    sync_single_git_repo(101)

    job = progress_tracker.get_snapshot(101)
    assert job is not None
    assert job["status"] == "synced"
    assert job["percent"] == 100
    assert any("already up-to-date" in log["message"] for log in job["logs"])


@patch("app.services.database.get_db_connection")
@patch("app.services.git_manager.get_remote_head_sha")
@patch("app.services.git_manager.shallow_clone_repo")
def test_git_syncer_clone_failure(mock_clone, mock_sha, mock_db):
    mock_conn = MagicMock()
    mock_db.return_value.__enter__.return_value = mock_conn
    mock_conn.execute.return_value.fetchone.return_value = {
        "id": 102, "name": "fail-clone-repo", "url": "https://github.com/test/fail.git",
        "branch": "main", "commit_sha": "old111", "auth_token": None, "auth_user": None, "provider": "github"
    }
    mock_sha.return_value = "new222"
    mock_clone.return_value = CloneResult(temp_dir=None, commit_sha=None, error="Authentication failed")

    sync_single_git_repo(102)

    job = progress_tracker.get_snapshot(102)
    assert job is not None
    assert job["status"] == "error"
    assert "Authentication failed" in job["error"]
    assert any("Failed to clone" in log["message"] for log in job["logs"])


@patch("app.services.indexing.state.trigger_list_changed_notification")
@patch("app.services.indexing.git_syncer.compute_git_repo_delta")
@patch("app.services.git_manager.shallow_clone_repo")
@patch("app.services.git_manager.get_remote_head_sha")
@patch("app.services.database.get_db_connection")
def test_git_syncer_empty_delta(mock_db, mock_sha, mock_clone, mock_delta, mock_notify, tmp_path):
    mock_conn = MagicMock()
    mock_db.return_value.__enter__.return_value = mock_conn
    mock_conn.execute.return_value.fetchone.return_value = {
        "id": 103, "name": "empty-delta-repo", "url": "https://github.com/test/empty.git",
        "branch": "main", "commit_sha": "old111", "auth_token": None, "auth_user": None, "provider": "github"
    }
    mock_sha.return_value = "new222"
    mock_clone.return_value = CloneResult(temp_dir=str(tmp_path), commit_sha="new222", error=None)
    mock_delta.return_value = ([], [], [], [str(tmp_path / "README.md")])

    sync_single_git_repo(103)

    job = progress_tracker.get_snapshot(103)
    assert job is not None
    assert job["status"] == "synced"
    assert job["percent"] == 100
    assert any("delta is empty" in log["message"] for log in job["logs"])


@patch("app.services.indexing.state.trigger_list_changed_notification")
@patch("app.services.indexing.processor.process_file_content")
@patch("app.services.vector_store.get_vector_store")
@patch("app.services.indexing.git_syncer.compute_git_repo_delta")
@patch("app.services.git_manager.shallow_clone_repo")
@patch("app.services.git_manager.get_remote_head_sha")
@patch("app.services.database.get_db_connection")
def test_git_syncer_full_5_stage_sync(
    mock_db, mock_sha, mock_clone, mock_delta, mock_store_getter, mock_proc, mock_notify, tmp_path
):
    mock_conn = MagicMock()
    mock_db.return_value.__enter__.return_value = mock_conn
    mock_conn.execute.return_value.fetchone.return_value = {
        "id": 104, "name": "full-sync-repo", "url": "https://github.com/test/full.git",
        "branch": "main", "commit_sha": "old111", "auth_token": None, "auth_user": None, "provider": "github"
    }
    mock_sha.return_value = "new222"

    file1 = tmp_path / "main.py"
    file1.write_text("print('hello')", encoding="utf-8")
    file2 = tmp_path / "utils.py"
    file2.write_text("def add(a, b): return a + b", encoding="utf-8")

    mock_clone.return_value = CloneResult(temp_dir=str(tmp_path), commit_sha="new222", error=None)
    mock_delta.return_value = ([str(file1), str(file2)], [], [], [])

    mock_store = MagicMock()
    mock_store.upsert_documents.return_value = True
    mock_store_getter.return_value = mock_store

    mock_proc.return_value = (
        [MagicMock()],
        [{"repo": "full-sync-repo", "filepath": "full-sync-repo://main.py", "name": "main", "full_symbol": "main", "kind": "func", "start_line": 1, "end_line": 1, "signature": "main()", "language": "python"}],
        ("full-sync-repo://main.py", "full-sync-repo", "Main", "", "code", "", "", "", 0.0),
        [],
        [],
        []
    )

    sync_single_git_repo(104)

    job = progress_tracker.get_snapshot(104)
    assert job is not None
    assert job["status"] == "synced"
    assert job["step"] == 5
    assert job["percent"] == 100
    assert job["processed_files"] == 2
    assert job["total_files"] == 2

    messages = [l["message"] for l in job["logs"]]
    assert any("Checking remote" in m for m in messages)
    assert any("Cloning branch" in m for m in messages)
    assert any("Delta computed" in m for m in messages)
    assert any("Ingested main.py" in m for m in messages)
    assert any("Successfully synced repo" in m for m in messages)


@patch("app.services.indexing.processor.process_file_content")
@patch("app.services.vector_store.get_vector_store")
@patch("app.services.indexing.git_syncer.compute_git_repo_delta")
@patch("app.services.git_manager.shallow_clone_repo")
@patch("app.services.git_manager.get_remote_head_sha")
@patch("app.services.database.get_db_connection")
def test_git_syncer_cancellation_during_stage_4(
    mock_db, mock_sha, mock_clone, mock_delta, mock_store_getter, mock_proc, tmp_path
):
    mock_conn = MagicMock()
    mock_db.return_value.__enter__.return_value = mock_conn
    mock_conn.execute.return_value.fetchone.return_value = {
        "id": 105, "name": "cancel-sync-repo", "url": "https://github.com/test/cancel.git",
        "branch": "main", "commit_sha": "old111", "auth_token": None, "auth_user": None, "provider": "github"
    }
    mock_sha.return_value = "new222"

    file1 = tmp_path / "a.py"
    file1.write_text("a = 1", encoding="utf-8")
    file2 = tmp_path / "b.py"
    file2.write_text("b = 2", encoding="utf-8")

    mock_clone.return_value = CloneResult(temp_dir=str(tmp_path), commit_sha="new222", error=None)
    mock_delta.return_value = ([str(file1), str(file2)], [], [], [])
    mock_store = MagicMock()
    mock_store_getter.return_value = mock_store

    def side_effect(*args, **kwargs):
        # Cancel job while processing first file
        progress_tracker.cancel_job(105)
        return ([], [], ("a", "b", "c", "d", "e", "f", "g", "h", 0.0), [], [], [])

    mock_proc.side_effect = side_effect

    sync_single_git_repo(105)

    job = progress_tracker.get_snapshot(105)
    assert job is not None
    assert job["cancelled"] is True
    assert job["status"] == "error"
    assert any("cancelled" in l["message"].lower() for l in job["logs"])


@patch("app.services.git_manager.get_remote_head_sha")
@patch("app.services.database.get_db_connection")
def test_git_syncer_unexpected_exception(mock_db, mock_sha):
    mock_conn = MagicMock()
    mock_db.return_value.__enter__.return_value = mock_conn
    mock_conn.execute.return_value.fetchone.return_value = {
        "id": 106, "name": "except-repo", "url": "https://github.com/test/err.git",
        "branch": "main", "commit_sha": "old111", "auth_token": None, "auth_user": None, "provider": "github"
    }
    mock_sha.side_effect = RuntimeError("Network timeout checking head SHA")

    sync_single_git_repo(106)

    job = progress_tracker.get_snapshot(106)
    assert job is not None
    assert job["status"] == "error"
    assert "Network timeout checking head SHA" in job["error"]
    assert any("Sync failed" in l["message"] for l in job["logs"])


@patch("app.services.database.get_db_connection")
def test_git_syncer_nonexistent_repo(mock_db):
    mock_conn = MagicMock()
    mock_db.return_value.__enter__.return_value = mock_conn
    mock_conn.execute.return_value.fetchone.return_value = None

    # Should not raise exception
    sync_single_git_repo(99999)
    assert progress_tracker.get_snapshot(99999) is None


def test_git_progress_tracker_pending_cancellation():
    tracker = GitProgressTracker()
    job = tracker.get_or_create_job(107, "pending-cancel-repo")
    assert job.status == "pending"
    cancelled = tracker.cancel_job(107)
    assert cancelled is True
    assert tracker.is_cancelled(107)
    snap = tracker.get_snapshot(107)
    assert snap["status"] == "error"
    assert snap["cancelled"] is True

