"""Unit and integration tests for Issues #178 and #179:
- Per-input token limit (max_tokens_per_input) truncation before batching
- HTTP 400 batch bisection, bad-chunk skipping with filepath logging, and uninterrupted repo sync
- Immediate pipeline producer/coalescer shutdown when the persist stage fails
"""

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import app.services.embeddings as emb_service
from app.models.schemas import CloneResult
from app.services.database import get_db_connection, init_db
from app.services.embedding_batcher import (
    estimate_token_count,
    execute_api_embeddings_batch,
    truncate_text_to_token_limit,
)
from app.services.indexing.channel_pipeline import (
    BoundedChannel,
    ChannelIngestionPipeline,
    ParsedFileItem,
)
from app.services.indexing.git_syncer import sync_single_git_repo
from app.services.vector_store import VectorDocument


def _make_fake_embedding_response(batch_slice, base_offset: float = 0.0):
    data = []
    for i, text in enumerate(batch_slice):
        val = float(text.split("-")[-1]) if "-" in text and text.split("-")[-1].isdigit() else float(i + base_offset)
        data.append(SimpleNamespace(index=i, embedding=[val, val + 0.5]))
    return SimpleNamespace(data=data)


def test_per_input_token_limit_truncates_oversized_chunk_before_batching(caplog):
    """Issue #178: Verifies oversized inputs exceeding max_tokens_per_input are truncated before batching and configurable via EMBEDDING_MAX_TOKENS_PER_INPUT."""
    oversized_text = "Repo: demo\nFile: src/giant.css\nLanguage: css\nSymbol: giant.css\nCode:\n" + ("a" * 40000)
    assert estimate_token_count(oversized_text) > 8000

    with caplog.at_level(logging.WARNING, logger="contextcortex.embeddings"):
        truncated = truncate_text_to_token_limit(oversized_text, max_tokens_per_input=8000, filepath="src/giant.css")

    assert len(truncated) == 8000 * 4
    assert estimate_token_count(truncated) == 8000
    assert any("src/giant.css" in rec.message for rec in caplog.records)

    received_inputs = []

    def fake_create(input, model):
        received_inputs.extend(input)
        return _make_fake_embedding_response(input)

    mock_client = MagicMock()
    mock_client.embeddings.create.side_effect = fake_create

    vecs = execute_api_embeddings_batch(
        client=mock_client,
        texts=[oversized_text, "short-text-1"],
        model_name="text-embedding-3-small",
        batch_size=128,
        max_concurrency=2,
        max_tokens_per_request=100000,
        max_tokens_per_input=1000,
    )
    assert len(vecs) == 2
    assert len(received_inputs) == 2
    assert len(received_inputs[0]) == 1000 * 4


def test_http_400_oversized_input_splits_batch_skips_bad_chunk_and_continues_sync(tmp_path, monkeypatch, caplog):
    """Issue #178: Verifies that on an HTTP 400 error for a batch, the batcher splits and retries halves, skips only the bad input, logs its file path, and completes the repo sync."""
    db_file = str(tmp_path / "test_400_bisect.db")
    monkeypatch.setenv("CACHE_DB_PATH", db_file)
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", db_file)
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", db_file)
    init_db()

    repo_dir = tmp_path / "repo_400"
    repo_dir.mkdir()
    for i in range(6):
        if i == 3:
            (repo_dir / f"file_{i}.py").write_text(
                "def bad_func():\n    return 'POISON_CHUNK_OVER_8192_TOKENS'\n",
                encoding="utf-8",
            )
        else:
            (repo_dir / f"file_{i}.py").write_text(
                f"def good_func_{i}():\n    return {i}\n",
                encoding="utf-8",
            )

    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO git_repositories (id, name, url, branch, commit_sha, status) VALUES (178, 'bisect-repo', 'https://github.com/org/bisect.git', 'main', 'old', 'pending')"
        )
        conn.commit()

    class FakeBadRequestError(Exception):
        def __init__(self, idx: int):
            super().__init__(f"Error code: 400 - Invalid 'input[{idx}]': maximum input length is 8192 tokens.")
            self.status_code = 400
            self.response = SimpleNamespace(status_code=400, headers={})

    def fake_create(input, model):
        for idx, text in enumerate(input):
            if "POISON_CHUNK_OVER_8192_TOKENS" in text or "file_3.py" in text:
                raise FakeBadRequestError(idx)
        return _make_fake_embedding_response(input)

    mock_client = MagicMock()
    mock_client.embeddings.create.side_effect = fake_create

    monkeypatch.setattr(emb_service, "EMBEDDING_PROVIDER", "api")
    monkeypatch.setattr(emb_service, "_openai_client", mock_client)
    monkeypatch.setattr(emb_service, "EMBEDDING_BATCH_SIZE", 128)
    monkeypatch.setattr(emb_service, "EMBEDDING_API_CONCURRENCY", 2)

    upserted_docs = []
    mock_store = MagicMock()
    mock_store.upsert_documents.side_effect = lambda docs, *a, **kw: (upserted_docs.extend(docs) or True)

    with caplog.at_level(logging.WARNING), \
         patch("app.services.git_manager.get_remote_head_sha", return_value="sha_178"), \
         patch("app.services.git_manager.shallow_clone_repo", return_value=CloneResult(temp_dir=str(repo_dir), commit_sha="sha_178", error=None)), \
         patch("app.services.git_manager.cleanup_repo_dir"), \
         patch("app.services.vector_store.get_vector_store", return_value=mock_store):
        ok = sync_single_git_repo(178)

    assert ok is True
    assert len(upserted_docs) == 5
    assert all(doc.dense_vector is not None for doc in upserted_docs)
    assert all(doc.rel_path != "file_3.py" for doc in upserted_docs)
    assert any("file_3.py" in rec.message for rec in caplog.records)


def test_pipeline_producer_stops_when_persist_stage_raises(tmp_path, monkeypatch, caplog):
    """Issue #179: Verifies that when the persist stage raises, the producer stops before reading all remaining files and threads are joined before executor shutdown."""
    db_file = str(tmp_path / "test_pipeline_stop.db")
    monkeypatch.setenv("CACHE_DB_PATH", db_file)
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", db_file)
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", db_file)
    init_db()

    mock_client = MagicMock()
    mock_client.embeddings.create.side_effect = lambda input, model: _make_fake_embedding_response(input)
    monkeypatch.setattr(emb_service, "EMBEDDING_PROVIDER", "api")
    monkeypatch.setattr(emb_service, "_openai_client", mock_client)

    produced_count = 0

    def _produce(channel: BoundedChannel[ParsedFileItem]) -> None:
        nonlocal produced_count
        for i in range(100):
            if channel.is_closed:
                break
            pt = VectorDocument(
                id=f"doc-{i}",
                dense_vector=None,
                sparse_indices=None,
                sparse_values=None,
                text=f"def fn_{i}(): return {i}",
                metadata={"_embed_text": f"chunk-{i}"},
            )
            item = ParsedFileItem(filepath=f"repo://f{i}.py", rel_path=f"f{i}.py", repo="repo", points=[pt])
            if not channel.write(item):
                break
            produced_count += 1

    def _failing_persist(items: list[ParsedFileItem]) -> None:
        raise RuntimeError("Simulated persist stage failure on batch 1")

    pipeline = ChannelIngestionPipeline(
        persist_batch_fn=_failing_persist,
        file_batch_size=2,
        parsed_channel_capacity=2,
        persist_channel_capacity=1,
    )

    with caplog.at_level(logging.ERROR), pytest.raises(RuntimeError, match="Simulated persist stage failure"):
        pipeline.run(_produce)

    assert produced_count < 25
    assert not any("cannot schedule new futures after shutdown" in rec.message for rec in caplog.records)


def test_partial_embedding_settings_update_preserves_provider_and_rolls_back_on_failure(tmp_path, monkeypatch):
    """Issue #183: Verifies partial update with only api_concurrency preserves provider=api, and a failed update rolls back without mutating saved settings or active client."""
    import builtins
    from app.models.schemas import EmbeddingSettingsRequest
    from app.services.database.connection import get_embedding_db_config

    db_file = str(tmp_path / "test_settings_183.db")
    monkeypatch.setenv("CACHE_DB_PATH", db_file)
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", db_file)
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", db_file)
    init_db()

    # 1. Configure provider=api with an API model
    emb_service.update_embedding_config(
        provider="api",
        dense_model="openai/text-embedding-3-small",
        api_concurrency=4,
        allow_fallback=False,
        rebuild_index=True,
    )
    orig_client = emb_service._openai_client
    assert emb_service.get_embedding_config()["provider"] == "api"

    # 2. Partial request payload with ONLY api_concurrency=8
    req = EmbeddingSettingsRequest(api_concurrency=8)
    assert req.provider is None

    updated = emb_service.update_embedding_config(
        provider=req.provider,
        dense_model=req.dense_model,
        api_concurrency=req.api_concurrency,
    )
    assert updated["provider"] == "api"
    assert updated["effective_provider"] == "api"
    assert updated["dense_model"] == "openai/text-embedding-3-small"
    assert updated["api_concurrency"] == 8
    assert get_embedding_db_config()["provider"] == "api"
    assert get_embedding_db_config()["api_concurrency"] == 8
    client_before_failed_update = emb_service._openai_client
    assert client_before_failed_update is not None

    # 3. Now simulate a failed update (switching to local when fastembed is missing and allow_fallback=False)
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "fastembed":
            raise ImportError("No module named 'fastembed'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(RuntimeError, match="Local FastEmbed initialization failed"):
        emb_service.update_embedding_config(
            provider="local",
            dense_model="openai/text-embedding-3-small",
            api_concurrency=16,
            allow_fallback=False,
            rebuild_index=True,
        )

    # Saved settings and in-memory active config must remain untouched
    cfg_after = emb_service.get_embedding_config()
    db_cfg_after = get_embedding_db_config()
    assert cfg_after["provider"] == "api"
    assert cfg_after["effective_provider"] == "api"
    assert cfg_after["dense_model"] == "openai/text-embedding-3-small"
    assert cfg_after["api_concurrency"] == 8
    assert db_cfg_after["provider"] == "api"
    assert db_cfg_after["api_concurrency"] == 8
    assert emb_service._openai_client is client_before_failed_update


@pytest.mark.asyncio
async def test_cancel_during_clone_stops_subprocess_updates_repo_status_and_sync_returns_409_when_locked(
    tmp_path, monkeypatch
):
    """Issue #184: Verifies cancelling during clone terminates the git subprocess, sets DB repo status to error, and POST /sync returns 409 while lock is held."""
    import subprocess
    from app.api.routers.repositories import api_sync_repo
    from app.services.git_manager import shallow_clone_repo
    from app.services.indexing.git_progress import progress_tracker
    from app.services.indexing.git_syncer import _get_repo_lock

    db_file = str(tmp_path / "test_cancel_clone_184.db")
    monkeypatch.setenv("CACHE_DB_PATH", db_file)
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", db_file)
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", db_file)
    init_db()

    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO git_repositories (id, name, url, branch, commit_sha, status) VALUES (184, 'clone-cancel-repo', 'https://github.com/org/large.git', 'main', 'old', 'pending')"
        )
        conn.commit()

    # 1. Verify POST /admin/api/repos/184/sync returns 409 when repo sync lock is held
    lock = _get_repo_lock(184)
    assert lock.acquire(blocking=False)
    try:
        resp = await api_sync_repo(184)
        assert getattr(resp, "status_code", 200) == 409
    finally:
        lock.release()

    # 2. Verify shallow_clone_repo terminates the subprocess when job is cancelled during clone
    progress_tracker.get_or_create_job(184, "clone-cancel-repo")
    terminated = []

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            self.cmd = cmd
            self.returncode = None

        def communicate(self, timeout=None):
            # Simulate cancel arriving during the first poll window
            progress_tracker.cancel_job(184)
            raise subprocess.TimeoutExpired(self.cmd, timeout or 0.2)

        def terminate(self):
            terminated.append(True)
            self.returncode = -15

        def wait(self, timeout=None):
            return self.returncode

        def kill(self):
            self.returncode = -9

    with patch("subprocess.Popen", side_effect=FakePopen):
        clone_res = shallow_clone_repo("https://github.com/org/large.git", "main", repo_id="184")

    assert terminated == [True]
    assert clone_res.temp_dir is None
    assert "cancelled" in (clone_res.error or "").lower()

    # 3. Verify sync_single_git_repo updates git_repositories.status in DB from 'syncing' to 'error' when cancelled after clone
    def clone_then_cancel(*args, **kwargs):
        progress_tracker.cancel_job(184)
        return CloneResult(temp_dir=str(tmp_path), commit_sha="new184", error=None)

    with patch("app.services.git_manager.get_remote_head_sha", return_value="new184"), \
         patch("app.services.git_manager.shallow_clone_repo", side_effect=clone_then_cancel), \
         patch("app.services.git_manager.cleanup_repo_dir"):
        sync_single_git_repo(184)

    with get_db_connection() as conn:
        row = conn.execute("SELECT status, last_error FROM git_repositories WHERE id = 184").fetchone()
    snap = progress_tracker.get_snapshot(184)
    assert row["status"] == "error"
    assert snap["status"] == "error"


def test_minified_css_dense_truncation_and_single_input_400_halving_retry():
    """Issue #185: Verifies minified CSS uses dense token truncation and single-input HTTP 400 errors truncate in half and retry until accepted instead of skipping."""
    minified_css = "Repo: web\nFile: dist/Mdm_To_Pub.css\nLanguage: css\nSymbol: Mdm_To_Pub.css\nCode:\n" + (
        ".btn-primary{color:#fff;background:#0055aa;padding:4px 8px;margin:0;border:1px solid #003366;}" * 1600
    )
    assert len(minified_css) > 140000

    first_truncated = truncate_text_to_token_limit(
        minified_css, max_tokens_per_input=8000, filepath="dist/Mdm_To_Pub.css"
    )
    # Dense punctuation ratio in minified CSS should truncate to <= 16000 chars (2 chars/token), not 32000
    assert len(first_truncated) <= 16000

    # Even if the upstream model still rejects inputs > 6000 chars with HTTP 400, single-input retry halves it until accepted
    class FakeLength400Error(Exception):
        def __init__(self):
            super().__init__("Error code: 400 - Invalid 'input[0]': maximum input length is 8192 tokens.")
            self.status_code = 400

    attempts = []

    def fake_create(input, model):
        for t in input:
            attempts.append(len(t))
            if len(t) > 6000:
                raise FakeLength400Error()
        return _make_fake_embedding_response(input)

    mock_client = MagicMock()
    mock_client.embeddings.create.side_effect = fake_create

    vecs = execute_api_embeddings_batch(
        client=mock_client,
        texts=["normal-chunk-0", minified_css],
        model_name="text-embedding-3-small",
        batch_size=128,
        max_concurrency=2,
        max_tokens_per_request=100000,
        max_tokens_per_input=8000,
        filepaths=["src/index.js", "dist/Mdm_To_Pub.css"],
    )
    # Both inputs must be embedded (neither is None / skipped)
    assert len(vecs) == 2
    assert vecs[0] is not None
    assert vecs[1] is not None
    assert any(length <= 6000 for length in attempts)


def test_pipeline_maintains_api_concurrency_overlap_without_clamping_to_1(tmp_path, monkeypatch):
    """Issue #186: Verifies ChannelIngestionPipeline runs up to api_concurrency=4 overlapping embedding requests in parallel and reports active_concurrency=4."""
    import threading
    import time
    from app.services.embedding_batcher import telemetry_tracker

    db_file = str(tmp_path / "test_conc_186.db")
    monkeypatch.setenv("CACHE_DB_PATH", db_file)
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", db_file)
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", db_file)
    init_db()

    telemetry_tracker.reset(target_concurrency=4)
    active = 0
    max_overlap = 0
    lock = threading.Lock()
    barrier = threading.Barrier(4, timeout=2.0)

    def fake_create(input, model):
        nonlocal active, max_overlap
        with lock:
            active += 1
            if active > max_overlap:
                max_overlap = active
        try:
            barrier.wait()
        except threading.BrokenBarrierError:
            pass
        time.sleep(0.02)
        with lock:
            active -= 1
        return _make_fake_embedding_response(input)

    mock_client = MagicMock()
    mock_client.embeddings.create.side_effect = fake_create

    monkeypatch.setattr(emb_service, "EMBEDDING_PROVIDER", "api")
    monkeypatch.setattr(emb_service, "_openai_client", mock_client)
    monkeypatch.setattr(emb_service, "EMBEDDING_BATCH_SIZE", 2)
    monkeypatch.setattr(emb_service, "EMBEDDING_API_CONCURRENCY", 4)

    def _produce(channel: BoundedChannel[ParsedFileItem]) -> None:
        for i in range(8):
            pt = VectorDocument(
                id=f"doc-{i}",
                dense_vector=None,
                sparse_indices=None,
                sparse_values=None,
                text=f"def fn_{i}(): return {i}",
                metadata={"_embed_text": f"chunk-{i}"},
            )
            channel.write(ParsedFileItem(filepath=f"repo://f{i}.py", rel_path=f"f{i}.py", repo="repo", points=[pt]))

    persisted = []
    pipeline = ChannelIngestionPipeline(
        persist_batch_fn=lambda items: persisted.extend(items),
        file_batch_size=8,
    )
    pipeline.run(_produce)

    assert len(persisted) == 8
    assert max_overlap == 4
    assert emb_service.get_embedding_config()["active_concurrency"] == 4

