"""Unit and integration tests for Issue #171: parallel API batch embeddings, token slicing, AIMD 429 control, cross-file batching, and atomic client swaps."""

import logging
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import app.services.embeddings as emb_service
import app.services.indexing.processor as proc_service
from app.models.schemas import CloneResult
from app.services.database import get_db_connection, init_db
from app.services.database.connection import get_embedding_db_config, get_metadata, set_embedding_db_config
from app.services.database.engine import get_db_engine
from app.services.embedding_batcher import (
    estimate_token_count,
    execute_api_embeddings_batch,
    partition_texts_into_slices,
    telemetry_tracker,
)
from app.services.indexing.git_syncer import sync_single_git_repo
from app.services.indexing.local_syncer import sync_local_paths
from app.services.indexing.progress import progress_tracker


def _make_fake_embedding_response(batch_slice, base_offset: float = 0.0):
    """Creates a mock OpenAI embeddings response where each vector encodes its input text index."""
    data = []
    for i, text in enumerate(batch_slice):
        val = float(text.split("-")[-1]) if "-" in text and text.split("-")[-1].isdigit() else float(i + base_offset)
        data.append(SimpleNamespace(index=i, embedding=[val, val + 0.5]))
    return SimpleNamespace(data=data)


def test_parallel_slices_execution_and_deterministic_ordering(monkeypatch):
    """Verifies get_dense_embeddings_batch dispatches slices in parallel across EMBEDDING_API_CONCURRENCY threads and reassembles results in exact input order."""
    telemetry_tracker.reset(target_concurrency=4)
    active_threads = 0
    max_observed_threads = 0
    lock = threading.Lock()
    barrier = threading.Barrier(4, timeout=2.0)

    def fake_create(input, model):
        nonlocal active_threads, max_observed_threads
        with lock:
            active_threads += 1
            if active_threads > max_observed_threads:
                max_observed_threads = active_threads
        try:
            barrier.wait()
        except threading.BrokenBarrierError:
            pass
        time.sleep(0.02)
        with lock:
            active_threads -= 1
        return _make_fake_embedding_response(input)

    mock_client = MagicMock()
    mock_client.embeddings.create.side_effect = fake_create

    monkeypatch.setattr(emb_service, "EMBEDDING_PROVIDER", "api")
    monkeypatch.setattr(emb_service, "_openai_client", mock_client)
    monkeypatch.setattr(emb_service, "EMBEDDING_BATCH_SIZE", 10)
    monkeypatch.setattr(emb_service, "EMBEDDING_API_CONCURRENCY", 4)
    monkeypatch.setattr(emb_service, "EMBEDDING_MAX_TOKENS_PER_REQUEST", 100000)
    monkeypatch.setattr(emb_service, "EMBEDDING_TPM_LIMIT", 0)

    texts = [f"chunk-{i}" for i in range(40)]
    results = emb_service.get_dense_embeddings_batch(texts)

    assert len(results) == 40
    assert mock_client.embeddings.create.call_count == 4
    assert max_observed_threads >= 2
    for i in range(40):
        assert results[i] == [float(i), float(i) + 0.5]


def test_token_limit_slicing_respects_max_tokens_per_request():
    """Verifies partition_texts_into_slices splits batches when estimated tokens exceed EMBEDDING_MAX_TOKENS_PER_REQUEST even if item count is below batch_size."""
    # Each text is 400 chars -> 100 estimated tokens
    texts = ["a" * 400 for _ in range(10)]
    assert estimate_token_count(texts[0]) == 100

    # Max 128 items, but max 250 tokens per request -> at most 2 items (200 tokens) per slice
    slices = partition_texts_into_slices(texts, max_items_per_slice=128, max_tokens_per_request=250)
    assert len(slices) == 5
    assert all(len(s) == 2 for s in slices)


def test_http_429_retry_after_aimd_and_telemetry(caplog):
    """Verifies HTTP 429 rate-limit responses parse Retry-After headers, log a warning, multiplicatively reduce concurrency, and record rate_limit_wait_seconds in telemetry and progress_tracker."""
    telemetry_tracker.reset(target_concurrency=4)
    progress_tracker.get_or_create_job(777, "rate-limit-repo")
    progress_tracker.update_step(777, 4, "Parsing Files", pct=60)

    class FakeRateLimitError(Exception):
        def __init__(self):
            super().__init__("429 Too Many Requests: RateLimitError")
            self.status_code = 429
            self.response = SimpleNamespace(status_code=429, headers={"Retry-After": "1.5"})

    calls = 0

    def fake_create(input, model):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise FakeRateLimitError()
        return _make_fake_embedding_response(input)

    mock_client = MagicMock()
    mock_client.embeddings.create.side_effect = fake_create
    slept_durations = []

    with caplog.at_level(logging.WARNING, logger="contextcortex.embeddings"):
        vecs = execute_api_embeddings_batch(
            client=mock_client,
            texts=["item-0", "item-1"],
            model_name="text-embedding-3-small",
            batch_size=128,
            max_concurrency=4,
            max_tokens_per_request=100000,
            sleep_fn=lambda s: slept_durations.append(s),
        )

    assert len(vecs) == 2
    assert slept_durations == [1.5]
    assert any("HTTP 429" in rec.message and "1.50s" in rec.message for rec in caplog.records)

    snap = telemetry_tracker.get_telemetry_snapshot(max_concurrency=4)
    assert snap["rate_limit_hits"] == 1
    assert snap["rate_limit_wait_seconds"] == pytest.approx(1.5, rel=1e-2)
    assert snap["chunks_embedded"] == 2
    # Concurrency dropped from 4 -> 2 on 429, and 1 success isn't 2 consecutive successes yet -> stays 2
    assert snap["active_concurrency"] == 2

    job_snap = progress_tracker.get_snapshot(777)
    assert job_snap["rate_limit_hits"] == 1
    assert job_snap["rate_limit_wait_seconds"] == pytest.approx(1.5, rel=1e-2)
    assert job_snap["chunks_embedded"] == 2

    # Two more consecutive slice successes should additively increase concurrency back from 2 -> 3
    execute_api_embeddings_batch(
        client=mock_client,
        texts=["item-2", "item-3"],
        model_name="text-embedding-3-small",
        batch_size=1,
        max_concurrency=4,
        sleep_fn=lambda s: None,
    )
    assert telemetry_tracker.get_effective_concurrency(4) >= 3


def test_cross_file_batch_embedding_in_git_and_local_syncer(tmp_path, monkeypatch):
    """Verifies git_syncer and local_syncer collect chunks across multiple files and call get_hybrid_embeddings_batch once per multi-file batch instead of once per file."""
    db_file = str(tmp_path / "test_cross_file.db")
    monkeypatch.setenv("CACHE_DB_PATH", db_file)
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", db_file)
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", db_file)
    init_db()

    repo_dir = tmp_path / "git_repo"
    repo_dir.mkdir()
    for i in range(10):
        (repo_dir / f"module_{i}.py").write_text(
            f"def func_{i}_a():\n    return {i}\n\ndef func_{i}_b():\n    return {i * 2}\n",
            encoding="utf-8",
        )

    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO git_repositories (id, name, url, branch, commit_sha, status) VALUES (1, 'batch-repo', 'https://github.com/org/batch.git', 'main', 'old', 'pending')"
        )
        conn.commit()

    embed_batch_Inputs = []

    def fake_hybrid_batch(texts):
        embed_batch_Inputs.append(list(texts))
        return [{"dense": [0.1] * 384, "sparse": None} for _ in texts]

    upserted_docs = []

    def fake_upsert(docs, *args, **kwargs):
        upserted_docs.extend(list(docs))
        return True

    mock_store = MagicMock()
    mock_store.upsert_documents.side_effect = fake_upsert

    with patch("app.services.git_manager.get_remote_head_sha", return_value="sha_new"), \
         patch("app.services.git_manager.shallow_clone_repo", return_value=CloneResult(temp_dir=str(repo_dir), commit_sha="sha_new", error=None)), \
         patch("app.services.git_manager.cleanup_repo_dir"), \
         patch("app.services.vector_store.get_vector_store", return_value=mock_store), \
         patch("app.services.indexing.processor.get_hybrid_embeddings_batch", side_effect=fake_hybrid_batch):
        ok = sync_single_git_repo(1)
        assert ok is True

    # All 10 files fit in a single BATCH_SIZE=50 batch -> 1 single call to get_hybrid_embeddings_batch!
    assert len(embed_batch_Inputs) == 1
    assert len(embed_batch_Inputs[0]) >= 10
    assert len(upserted_docs) >= 10
    assert all(doc.dense_vector == [0.1] * 384 for doc in upserted_docs)
    assert all("_embed_text" not in doc.metadata for doc in upserted_docs)

    # Also verify local_syncer cross-file batching
    local_dir = tmp_path / "local_notes"
    local_dir.mkdir()
    for i in range(6):
        (local_dir / f"note_{i}.md").write_text(f"# Heading {i}\n\nUnique paragraph content for note {i}.", encoding="utf-8")

    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO indexed_paths (path, type, recursive, enabled, repo, category) VALUES (?, 'directory', 1, 1, 'local-batch', 'docs')",
            (str(local_dir),),
        )
        conn.commit()

    embed_batch_Inputs.clear()
    with patch("app.services.vector_store.get_vector_store", return_value=mock_store), \
         patch("app.services.indexing.processor.get_hybrid_embeddings_batch", side_effect=fake_hybrid_batch):
        assert sync_local_paths(force=True, repo="local-batch") is True

    assert len(embed_batch_Inputs) == 1
    assert len(embed_batch_Inputs[0]) == 6


def test_atomic_openai_client_swap_during_concurrent_embeddings(monkeypatch):
    """Verifies init_embeddings replaces _openai_client atomically without ever setting it to None while concurrent embedding calls are active."""
    monkeypatch.setenv("EMBEDDING_PROVIDER", "api")
    monkeypatch.setattr(emb_service, "EMBEDDING_PROVIDER", "api")
    monkeypatch.setattr(emb_service, "DENSE_MODEL_NAME", emb_service.DENSE_MODEL_NAME)
    monkeypatch.setattr(emb_service, "_dense_model", emb_service._dense_model)
    monkeypatch.setattr(emb_service, "_sparse_model", emb_service._sparse_model)

    client_v1 = MagicMock()
    client_v1.embeddings.create.side_effect = lambda input, model: _make_fake_embedding_response(input)
    monkeypatch.setattr(emb_service, "_openai_client", client_v1)

    errors = []
    stop_event = threading.Event()

    def worker():
        while not stop_event.is_set():
            try:
                res = emb_service.get_dense_embeddings_batch(["concurrent-0", "concurrent-1"])
                if len(res) != 2:
                    errors.append(f"Unexpected length: {len(res)}")
            except Exception as e:
                errors.append(e)

    def slow_openai_ctor(*args, **kwargs):
        time.sleep(0.03)
        c = MagicMock()
        c.embeddings.create.side_effect = lambda input, model: _make_fake_embedding_response(input)
        return c

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for t in threads:
        t.start()

    try:
        with patch("openai.OpenAI", side_effect=slow_openai_ctor):
            for _ in range(4):
                emb_service.init_embeddings(provider="api", dense_model="text-embedding-3-small")
    finally:
        stop_event.set()
        for t in threads:
            t.join(timeout=2.0)

    assert not errors, f"Concurrent embedding calls failed during init_embeddings swap: {errors}"


def test_env_embedding_batch_size_takes_effect_across_restarts(tmp_path, monkeypatch):
    """Verifies init_db does not freeze embedding_batch_size or embedding_num_threads in system_metadata, allowing .env changes to take effect on restart."""
    db_file = tmp_path / "restart_env.db"
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.delenv("EMBEDDING_BATCH_SIZE", raising=False)
    monkeypatch.setenv("EMBEDDING_PROVIDER", "api")

    engine = get_db_engine(db_url, reset=True)
    init_db(engine=engine)

    # Neither embedding_batch_size nor embedding_num_threads should be seeded into system_metadata on startup
    assert get_metadata("embedding_batch_size") is None
    assert get_metadata("embedding_num_threads") is None

    # Default for API provider when EMBEDDING_BATCH_SIZE is unset is 128
    cfg1 = get_embedding_db_config()
    assert cfg1["batch_size"] == 128

    # Simulate changing EMBEDDING_BATCH_SIZE in .env and restarting against the same database
    monkeypatch.setenv("EMBEDDING_BATCH_SIZE", "96")
    init_db(engine=engine)
    cfg2 = get_embedding_db_config()
    assert cfg2["batch_size"] == 96

    # Explicit save via Admin UI/API persists override in system_metadata
    set_embedding_db_config(batch_size=64)
    assert get_metadata("embedding_batch_size") == "64"
    assert get_embedding_db_config()["batch_size"] == 64


def test_bounded_channel_pipeline_producer_consumer_backpressure(tmp_path, monkeypatch):
    """Verifies BoundedChannel and ChannelIngestionPipeline stream parsed files through coalescing, parallel API embedding slices, and persistence."""
    from app.services.indexing.channel_pipeline import (
        BoundedChannel,
        ChannelIngestionPipeline,
        ParsedFileItem,
    )
    from app.services.vector_store import VectorDocument

    db_file = str(tmp_path / "test_channel_pipeline.db")
    monkeypatch.setenv("CACHE_DB_PATH", db_file)
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", db_file)
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", db_file)
    init_db()

    mock_client = MagicMock()
    mock_client.embeddings.create.side_effect = lambda input, model: _make_fake_embedding_response(input)

    monkeypatch.setattr(emb_service, "EMBEDDING_PROVIDER", "api")
    monkeypatch.setattr(emb_service, "_openai_client", mock_client)
    monkeypatch.setattr(emb_service, "EMBEDDING_BATCH_SIZE", 4)
    monkeypatch.setattr(emb_service, "EMBEDDING_API_CONCURRENCY", 2)

    persisted_batches = []

    def _produce(channel: BoundedChannel[ParsedFileItem]) -> None:
        for i in range(6):
            pt = VectorDocument(
                id=f"doc-{i}",
                dense_vector=None,
                sparse_indices=None,
                sparse_values=None,
                text=f"def fn_{i}(): return {i}",
                metadata={"_embed_text": f"chunk-{i}"},
            )
            channel.write(ParsedFileItem(filepath=f"repo://f{i}.py", rel_path=f"f{i}.py", repo="repo", points=[pt]))

    pipeline = ChannelIngestionPipeline(
        persist_batch_fn=lambda items: persisted_batches.append(list(items)),
        file_batch_size=3,
        parsed_channel_capacity=2,
        persist_channel_capacity=2,
    )
    pipeline.run(_produce)

    assert len(persisted_batches) == 2
    all_pts = [pt for batch in persisted_batches for item in batch for pt in item.points]
    assert len(all_pts) == 6
    assert all(pt.dense_vector is not None for pt in all_pts)
    assert all("_embed_text" not in pt.metadata for pt in all_pts)


def test_class_and_methods_do_not_double_chunk():
    """Verifies extract_symbols_and_chunks does not duplicate method bodies inside parent class chunks and keeps method chunk hashes stable when sibling methods change."""
    from app.services.chunking.symbol_extractor import extract_symbols_and_chunks

    code_v1 = (
        "class OrderProcessor:\n"
        "    DEFAULT_TAX = 0.07\n"
        "\n"
        "    def calculate_subtotal(self, items):\n"
        "        return sum(x.price for x in items)\n"
        "\n"
        "    def calculate_total(self, items):\n"
        "        sub = self.calculate_subtotal(items)\n"
        "        return sub * (1.0 + self.DEFAULT_TAX)\n"
    )
    res_v1 = extract_symbols_and_chunks(code_v1, "order.py", repo="repo")
    symbol_names = {s.name for s in res_v1.symbols}
    assert {"OrderProcessor", "calculate_subtotal", "calculate_total"} <= symbol_names

    class_chunks = [c for c in res_v1.chunks if c.symbol == "OrderProcessor"]
    subtotal_chunks = [c for c in res_v1.chunks if c.symbol == "OrderProcessor.calculate_subtotal"]
    total_chunks = [c for c in res_v1.chunks if c.symbol == "OrderProcessor.calculate_total"]

    assert len(class_chunks) == 1
    assert len(subtotal_chunks) == 1
    assert len(total_chunks) == 1

    # Parent class chunk contains class header & attribute, NOT the method bodies
    assert "DEFAULT_TAX = 0.07" in class_chunks[0].content
    assert "def calculate_subtotal" not in class_chunks[0].content
    assert "def calculate_total" not in class_chunks[0].content

    # Editing calculate_total (and shifting lines) does not alter calculate_subtotal's chunk content hash
    code_v2 = (
        "# Added header comment shifting all line numbers down\n"
        "# Second comment line\n"
        "class OrderProcessor:\n"
        "    DEFAULT_TAX = 0.07\n"
        "\n"
        "    def calculate_subtotal(self, items):\n"
        "        return sum(x.price for x in items)\n"
        "\n"
        "    def calculate_total(self, items):\n"
        "        sub = self.calculate_subtotal(items)\n"
        "        discount = 5.0\n"
        "        return max(0.0, sub - discount) * (1.0 + self.DEFAULT_TAX)\n"
    )
    res_v2 = extract_symbols_and_chunks(code_v2, "order.py", repo="repo")
    subtotal_v2 = [c for c in res_v2.chunks if c.symbol == "OrderProcessor.calculate_subtotal"][0]
    assert proc_service.compute_text_hash(subtotal_chunks[0].content.strip()) == proc_service.compute_text_hash(
        subtotal_v2.content.strip()
    )


