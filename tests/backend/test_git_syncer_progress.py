import pytest
from unittest.mock import patch, MagicMock
from app.models.schemas import CloneResult
from app.services.database import init_db, get_db_connection
from app.services.indexing.git_progress import progress_tracker, GitProgressTracker
from app.services.indexing.git_syncer import sync_single_git_repo
import app.services.indexing.processor as proc_service


@pytest.fixture(autouse=True)
def isolated_progress_env(tmp_path, monkeypatch):
    db_file = str(tmp_path / "test_git_progress.db")
    monkeypatch.setenv("CACHE_DB_PATH", db_file)
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", db_file)
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", db_file)
    init_db()

    tracker = GitProgressTracker()
    with tracker._lock:
        tracker.jobs.clear()
    yield
    with tracker._lock:
        tracker.jobs.clear()


def _insert_repo(repo_id: int, name: str, commit_sha: str | None = "old111") -> None:
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO git_repositories (id, name, url, branch, commit_sha, status)
               VALUES (?, ?, 'https://github.com/test/repo.git', 'main', ?, 'pending')""",
            (repo_id, name, commit_sha),
        )
        conn.commit()


@patch("app.services.git_manager.get_remote_head_sha", return_value="abc123456")
def test_git_syncer_reports_stages_up_to_date(mock_sha):
    _insert_repo(101, "up-to-date-repo", commit_sha="abc123456")

    sync_single_git_repo(101)

    job = progress_tracker.get_snapshot(101)
    assert job is not None
    assert job["status"] == "synced"
    assert job["percent"] == 100
    assert any("already up-to-date" in log["message"] for log in job["logs"])


@patch("app.services.git_manager.get_remote_head_sha", return_value="new222")
@patch("app.services.git_manager.shallow_clone_repo")
def test_git_syncer_clone_failure(mock_clone, mock_sha):
    _insert_repo(102, "fail-clone-repo", commit_sha="old111")
    mock_clone.return_value = CloneResult(temp_dir=None, commit_sha=None, error="Authentication failed")

    sync_single_git_repo(102)

    job = progress_tracker.get_snapshot(102)
    assert job is not None
    assert job["status"] == "error"
    assert "Authentication failed" in job["error"]
    assert any("Failed to clone" in log["message"] for log in job["logs"])


@patch("app.services.git_manager.get_remote_head_sha", return_value="new222")
@patch("app.services.git_manager.shallow_clone_repo")
@patch("app.services.git_manager.cleanup_repo_dir")
@patch("app.services.vector_store.get_vector_store")
def test_git_syncer_full_5_stage_sync(mock_store_getter, mock_cleanup, mock_clone, mock_sha, tmp_path):
    _insert_repo(104, "full-sync-repo", commit_sha="old111")

    repo_dir = tmp_path / "repo_104"
    repo_dir.mkdir()
    (repo_dir / "main.py").write_text("def main():\n    return 'hello'\n", encoding="utf-8")
    (repo_dir / "utils.py").write_text("def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")

    mock_clone.return_value = CloneResult(temp_dir=str(repo_dir), commit_sha="new222", error=None)
    mock_store = MagicMock()
    mock_store.upsert_documents.return_value = True
    mock_store_getter.return_value = mock_store

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

    with get_db_connection() as conn:
        syms = [r["name"] for r in conn.execute("SELECT name FROM ast_symbols WHERE repo = 'full-sync-repo'").fetchall()]
        assert "main" in syms
        assert "add" in syms


@patch("app.services.git_manager.get_remote_head_sha", return_value="new222")
@patch("app.services.git_manager.shallow_clone_repo")
@patch("app.services.git_manager.cleanup_repo_dir")
@patch("app.services.vector_store.get_vector_store")
def test_git_syncer_cancellation_during_stage_4(mock_store_getter, mock_cleanup, mock_clone, mock_sha, tmp_path, monkeypatch):
    _insert_repo(105, "cancel-sync-repo", commit_sha="old111")

    repo_dir = tmp_path / "repo_105"
    repo_dir.mkdir()
    (repo_dir / "a.py").write_text("def a(): return 1\n", encoding="utf-8")
    (repo_dir / "b.py").write_text("def b(): return 2\n", encoding="utf-8")

    mock_clone.return_value = CloneResult(temp_dir=str(repo_dir), commit_sha="new222", error=None)
    mock_store = MagicMock()
    mock_store.upsert_documents.return_value = True
    mock_store_getter.return_value = mock_store

    orig_process = proc_service.process_file_content

    def cancel_after_first(*args, **kwargs):
        res = orig_process(*args, **kwargs)
        progress_tracker.cancel_job(105)
        return res

    monkeypatch.setattr(proc_service, "process_file_content", cancel_after_first)

    sync_single_git_repo(105)

    job = progress_tracker.get_snapshot(105)
    assert job is not None
    assert job["cancelled"] is True
    assert job["status"] == "error"
    assert any("cancelled" in l["message"].lower() for l in job["logs"])


def test_git_syncer_nonexistent_repo():
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


@patch("app.services.git_manager.get_remote_head_sha", return_value="new333")
@patch("app.services.git_manager.shallow_clone_repo")
@patch("app.services.vector_store.get_vector_store")
def test_git_syncer_failure_stops_producer_keeps_error_status_and_only_counts_persisted_files(
    mock_store_getter, mock_clone, mock_sha, tmp_path, caplog
):
    """Issues #179 & #180: Verifies that when batch 2 fails in the persist stage:
    1. The producer stops before reading all remaining files and logs no 'No such file or directory' after temp_dir cleanup.
    2. Only batch 1 files (actually saved to DB) are counted in processed_files and logged as 'Ingested'.
    3. sync-status remains 'error' matching the repository table record.
    """
    import logging
    import shutil

    _insert_repo(180, "partial-fail-repo", commit_sha="old111")

    repo_dir = tmp_path / "repo_180"
    repo_dir.mkdir()
    for i in range(60):
        (repo_dir / f"mod_{i:03d}.py").write_text(f"def fn_{i}():\n    return {i}\n", encoding="utf-8")

    mock_clone.return_value = CloneResult(temp_dir=str(repo_dir), commit_sha="new333", error=None)

    upsert_calls = 0

    def upsert_side_effect(docs):
        nonlocal upsert_calls
        upsert_calls += 1
        if upsert_calls == 1:
            return True
        raise RuntimeError("Batch 2 persist failure")

    mock_store = MagicMock()
    mock_store.upsert_documents.side_effect = upsert_side_effect
    mock_store_getter.return_value = mock_store

    with caplog.at_level(logging.ERROR), \
         patch("app.services.git_manager.cleanup_repo_dir", side_effect=lambda d: shutil.rmtree(d, ignore_errors=True)):
        res = sync_single_git_repo(180)

    assert not res
    # No 'No such file or directory' errors logged after temp_dir cleanup
    assert not any("No such file or directory" in rec.message for rec in caplog.records)

    job = progress_tracker.get_snapshot(180)
    assert job is not None
    # Status must remain 'error' (not overwritten back to 'syncing' by producer)
    assert job["status"] == "error"
    assert "Batch 2 persist failure" in (job["error"] or "")

    # Only batch 1 (25 files) was persisted to the database
    with get_db_connection() as conn:
        repo_row = conn.execute("SELECT status, last_error FROM git_repositories WHERE id = 180").fetchone()
        saved_files_count = conn.execute("SELECT COUNT(*) FROM indexed_files WHERE repo = 'partial-fail-repo'").fetchone()[0]

    assert repo_row["status"] == "error"
    assert saved_files_count == 25
    assert job["processed_files"] == 25

    ingested_logs = [l["message"] for l in job["logs"] if "Ingested mod_" in l["message"]]
    assert len(ingested_logs) == 25

