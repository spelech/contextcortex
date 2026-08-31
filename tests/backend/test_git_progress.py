import pytest
import asyncio
from collections import deque
from app.services.indexing.git_progress import GitSyncJob, GitProgressTracker, progress_tracker


def test_job_dataclass_defaults_and_to_dict():
    job = GitSyncJob(repo_id=1, repo_name="my-repo")
    assert job.repo_id == 1
    assert job.repo_name == "my-repo"
    assert job.status == "pending"
    assert job.step == 1
    assert job.total_steps == 5
    assert job.step_name == "Connecting & Remote Check"
    assert job.current_file is None
    assert job.processed_files == 0
    assert job.total_files == 0
    assert job.percent == 0
    assert job.error is None
    assert isinstance(job.logs, deque)
    assert job.logs.maxlen == 300
    assert job.cancelled is False

    job.logs.append({"timestamp": "12:00:00", "level": "INFO", "message": "hello"})
    d = job.to_dict()
    assert isinstance(d, dict)
    assert isinstance(d["logs"], list)
    assert len(d["logs"]) == 1
    assert d["logs"][0]["message"] == "hello"


def test_tracker_singleton():
    t1 = GitProgressTracker()
    t2 = GitProgressTracker()
    assert t1 is t2
    assert t1 is progress_tracker


def test_tracker_job_lifecycle():
    tracker = GitProgressTracker()
    job = tracker.get_or_create_job(10, "repo-lifecycle")
    assert job.status == "pending"
    assert job.step == 1
    assert job.total_steps == 5

    # Step update with explicit pct
    tracker.update_step(10, 2, "Shallow Cloning", processed=1, total=1, pct=25)
    assert job.status == "syncing"
    assert job.step == 2
    assert job.step_name == "Shallow Cloning"
    assert job.percent == 25
    assert job.processed_files == 1
    assert job.total_files == 1

    # Step update with calculated pct
    tracker.update_step(10, 4, "Parsing Files", current_file="app/main.py", processed=5, total=10)
    assert job.step == 4
    assert job.current_file == "app/main.py"
    assert job.processed_files == 5
    assert job.total_files == 10
    # base_pct for step 4 = ((4-1)/5)*100 = 60, step_range = 100/5 = 20. 60 + int(5/10 * 20) = 70
    assert job.percent == 70

    # Logging
    tracker.log(10, "info", "File parsed")
    assert len(job.logs) == 1
    assert job.logs[0]["level"] == "INFO"
    assert job.logs[0]["message"] == "File parsed"

    # Finish job as synced
    tracker.finish_job(10, "synced")
    assert job.status == "synced"
    assert job.step == 5
    assert job.percent == 100
    assert job.step_name == "Sync Complete"
    assert job.error is None


def test_tracker_finish_job_with_error():
    tracker = GitProgressTracker()
    job = tracker.get_or_create_job(20, "error-repo")
    tracker.update_step(20, 2, "Shallow Cloning", pct=20)
    tracker.finish_job(20, status="error", error="Authentication failed")
    assert job.status == "error"
    assert job.error == "Authentication failed"
    assert job.percent == 20


def test_tracker_log_ring_buffer_limit():
    tracker = GitProgressTracker()
    tracker.get_or_create_job(30, "log-limit-repo")
    for i in range(350):
        tracker.log(30, "debug", f"Log message {i}")

    snap = tracker.get_snapshot(30)
    assert len(snap["logs"]) == 300
    assert snap["logs"][0]["message"] == "Log message 50"
    assert snap["logs"][-1]["message"] == "Log message 349"


def test_tracker_job_reset():
    tracker = GitProgressTracker()
    tracker.get_or_create_job(40, "reset-repo")
    tracker.update_step(40, 3, "Computing Delta", pct=40)
    tracker.finish_job(40, "synced")
    assert tracker.get_snapshot(40)["status"] == "synced"

    # Restarting sync for same repo
    job2 = tracker.get_or_create_job(40, "reset-repo-renamed")
    assert job2.repo_name == "reset-repo-renamed"
    assert job2.status == "syncing"
    assert job2.step == 1
    assert job2.percent == 0
    assert job2.error is None
    assert job2.cancelled is False


def test_tracker_cancellation():
    tracker = GitProgressTracker()
    tracker.get_or_create_job(50, "cancel-repo")
    tracker.update_step(50, 2, "Cloning", pct=20)
    assert not tracker.is_cancelled(50)

    cancelled = tracker.cancel_job(50)
    assert cancelled is True
    assert tracker.is_cancelled(50)

    snap = tracker.get_snapshot(50)
    assert snap["status"] == "error"
    assert snap["cancelled"] is True
    assert snap["error"] == "Sync cancelled by user"

    # Cancelling again when not syncing returns False
    assert tracker.cancel_job(50) is False
    # Cancelling non-existent repo returns False
    assert tracker.cancel_job(99999) is False
    assert tracker.is_cancelled(99999) is False


def test_tracker_snapshots():
    tracker = GitProgressTracker()
    tracker.get_or_create_job(60, "snap-repo-1")
    tracker.get_or_create_job(61, "snap-repo-2")

    single = tracker.get_snapshot(60)
    assert single is not None
    assert single["repo_id"] == 60

    missing = tracker.get_snapshot(99999)
    assert missing is None

    all_snapshots = tracker.get_snapshot()
    assert isinstance(all_snapshots, dict)
    assert 60 in all_snapshots
    assert 61 in all_snapshots


def test_tracker_nonexistent_repo_safe_handling():
    tracker = GitProgressTracker()
    # Should not raise exceptions
    tracker.update_step(88888, 2, "Some Step")
    tracker.log(88888, "INFO", "Lost message")
    tracker.finish_job(88888, "synced")


@pytest.mark.asyncio
async def test_tracker_subscription_and_broadcast():
    tracker = GitProgressTracker()
    queue = tracker.subscribe()

    tracker.get_or_create_job(70, "broadcast-repo")
    evt1 = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert evt1["type"] == "progress"
    assert evt1["data"]["repo_id"] == 70

    tracker.update_step(70, 2, "Cloning", pct=25)
    evt2 = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert evt2["type"] == "progress"
    assert evt2["data"]["step"] == 2
    assert evt2["data"]["percent"] == 25

    tracker.log(70, "INFO", "Broadcast log line")
    evt3 = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert evt3["type"] == "log"
    assert evt3["repo_id"] == 70
    assert evt3["data"]["message"] == "Broadcast log line"

    tracker.unsubscribe(queue)
    tracker.log(70, "INFO", "After unsubscribe")
    assert queue.empty()
