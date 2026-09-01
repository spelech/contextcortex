import json
import asyncio
from unittest.mock import MagicMock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.routes import router
from app.api.routers.repositories import api_stream_repo_sync
import app.api.routers.repositories as repo_router_module
from app.services.indexing.git_progress import progress_tracker

app = FastAPI()
app.include_router(router)
client = TestClient(app)


def test_get_sync_status_single_repo_found():
    progress_tracker.get_or_create_job(101, "api-repo-101")
    progress_tracker.update_step(101, 3, "Computing Delta", pct=45)
    progress_tracker.log(101, "INFO", "Sample api log line")

    resp = client.get("/admin/api/repos/101/sync-status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["repo_id"] == 101
    assert data["step"] == 3
    assert data["percent"] == 45
    assert len(data["logs"]) >= 1
    assert data["logs"][0]["message"] == "Sample api log line"


def test_get_sync_status_single_repo_not_found():
    resp = client.get("/admin/api/repos/99999/sync-status")
    assert resp.status_code == 404
    assert "error" in resp.json()


def test_get_sync_status_all_repos():
    progress_tracker.get_or_create_job(201, "repo-201")
    progress_tracker.get_or_create_job(202, "repo-202")

    resp = client.get("/admin/api/repos/sync-status")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    assert "201" in data or 201 in data
    assert "202" in data or 202 in data


def test_cancel_sync_endpoint_success():
    progress_tracker.get_or_create_job(301, "cancel-api-repo")
    progress_tracker.update_step(301, 2, "Shallow Cloning", pct=20)

    resp = client.post("/admin/api/repos/301/cancel-sync")
    assert resp.status_code == 200
    assert resp.json() == {"status": "cancelled", "repo_id": 301}
    assert progress_tracker.is_cancelled(301) is True


def test_cancel_sync_endpoint_not_syncing_or_invalid():
    # Non-existent repo
    resp = client.post("/admin/api/repos/88888/cancel-sync")
    assert resp.status_code == 400
    assert "error" in resp.json()

    # Finished repo
    progress_tracker.get_or_create_job(302, "finished-repo")
    progress_tracker.finish_job(302, "synced")
    resp2 = client.post("/admin/api/repos/302/cancel-sync")
    assert resp2.status_code == 400
    assert "error" in resp2.json()


@pytest.mark.asyncio
async def test_sse_stream_initial_snapshot_and_headers():
    progress_tracker.get_or_create_job(401, "stream-repo-401")
    mock_request = MagicMock()
    mock_request.is_disconnected.return_value = False

    resp = await api_stream_repo_sync(mock_request)
    assert resp.status_code == 200
    assert resp.media_type == "text/event-stream"
    assert "no-cache" in resp.headers.get("cache-control", "")
    assert resp.headers.get("connection") == "keep-alive"
    assert resp.headers.get("x-accel-buffering") == "no"

    gen = resp.body_iterator
    init_chunk = await gen.__anext__()
    assert init_chunk.startswith("event: init\n")
    assert "stream-repo-401" in init_chunk

    await gen.aclose()


@pytest.mark.asyncio
async def test_sse_stream_live_events_and_unsubscription():
    initial_sub_count = len(progress_tracker.subscribers)
    mock_request = MagicMock()
    mock_request.is_disconnected.return_value = False

    resp = await api_stream_repo_sync(mock_request)
    assert len(progress_tracker.subscribers) == initial_sub_count + 1

    gen = resp.body_iterator
    init_chunk = await gen.__anext__()
    assert "event: init" in init_chunk

    # Trigger progress update
    progress_tracker.get_or_create_job(501, "stream-live-repo")
    prog_chunk = await gen.__anext__()
    assert "event: progress" in prog_chunk
    assert "stream-live-repo" in prog_chunk

    # Trigger log update
    progress_tracker.log(501, "INFO", "Test streaming log message")
    log_chunk = await gen.__anext__()
    assert "event: log" in log_chunk
    assert "Test streaming log message" in log_chunk

    # Close generator cleanly and verify subscriber removal
    await gen.aclose()
    assert len(progress_tracker.subscribers) == initial_sub_count


@pytest.mark.asyncio
async def test_sse_stream_keep_alive_ping(monkeypatch):
    monkeypatch.setattr(repo_router_module, "STREAM_KEEPALIVE_TIMEOUT", 0.02)
    mock_request = MagicMock()
    mock_request.is_disconnected.return_value = False

    resp = await api_stream_repo_sync(mock_request)
    gen = resp.body_iterator
    init_chunk = await gen.__anext__()
    assert "event: init" in init_chunk

    # When queue is empty, next chunk after timeout is keep-alive ping
    ping_chunk = await gen.__anext__()
    assert ping_chunk == ": keep-alive ping\n\n"

    await gen.aclose()
