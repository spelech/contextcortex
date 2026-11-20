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
            if "POISON_CHUNK_OVER_8192_TOKENS" in text:
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
