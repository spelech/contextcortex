import hashlib
from unittest.mock import patch, MagicMock
import pytest
from app.services.indexing.processor import process_file_content, compute_text_hash
from app.services.database.connection import init_db
from app.services.database.embedding_cache import (
    get_cached_embeddings_batch,
    set_cached_embeddings_batch,
)
from app.services.embeddings import DENSE_MODEL_NAME

@pytest.fixture(autouse=True)
def setup_db(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_proc.db")
    monkeypatch.setenv("CACHE_DB_PATH", test_db)
    init_db()

def test_compute_text_hash():
    sample = "def test_func():\n    return 42\n"
    expected = hashlib.sha256(sample.encode("utf-8")).hexdigest()
    assert compute_text_hash(sample) == expected
    assert compute_text_hash("") == hashlib.sha256(b"").hexdigest()
    assert compute_text_hash("こんにちは") == hashlib.sha256("こんにちは".encode("utf-8")).hexdigest()

def test_process_file_content_populates_embedding_cache():
    code = "def hello():\n    return 'world'\n"
    points, symbols, summary, rels, routes, calls = process_file_content(
        filepath="test_repo://hello.py",
        rel_path="hello.py",
        content=code,
        repo="test_repo",
        doc_type="code"
    )
    assert len(points) > 0
    assert points[0].dense_vector is not None

    chunk_hash = compute_text_hash(points[0].text)
    cached = get_cached_embeddings_batch([chunk_hash], model_name=DENSE_MODEL_NAME)
    assert chunk_hash in cached
    assert cached[chunk_hash]["dense"] == points[0].dense_vector

def test_process_file_content_uses_cached_embeddings():
    code = "def cached_func():\n    return 'already_cached'\n"
    # Pre-compute chunk text and pre-seed cache
    chunk_text = code.strip()
    chunk_hash = compute_text_hash(chunk_text)
    dummy_dense = [0.123] * 384
    dummy_sparse_indices = [1, 5, 10]
    dummy_sparse_values = [0.1, 0.5, 0.9]

    set_cached_embeddings_batch([{
        "chunk_hash": chunk_hash,
        "dense_vector": dummy_dense,
        "sparse_indices": dummy_sparse_indices,
        "sparse_values": dummy_sparse_values,
        "model_name": DENSE_MODEL_NAME,
    }])

    with patch("app.services.indexing.processor.get_hybrid_embeddings_batch") as mock_embed:
        points, symbols, summary, rels, routes, calls = process_file_content(
            filepath="test_repo://cached.py",
            rel_path="cached.py",
            content=code,
            repo="test_repo",
            doc_type="code"
        )
        # Embedding function should NOT be called on full cache hit
        mock_embed.assert_not_called()

    assert len(points) == 1
    assert points[0].dense_vector == dummy_dense
    assert points[0].sparse_indices == dummy_sparse_indices
    assert points[0].sparse_values == dummy_sparse_values

def test_process_file_content_partial_cache_miss():
    chunk1 = "def first_func():\n    return 1"
    chunk2 = "def second_func():\n    return 2"
    code = f"{chunk1}\n\n{chunk2}\n"

    # Pre-cache only chunk1
    hash1 = compute_text_hash(chunk1)
    dummy_dense1 = [0.111] * 384
    set_cached_embeddings_batch([{
        "chunk_hash": hash1,
        "dense_vector": dummy_dense1,
        "sparse_indices": None,
        "sparse_values": None,
        "model_name": DENSE_MODEL_NAME,
    }])

    points, symbols, summary, rels, routes, calls = process_file_content(
        filepath="test_repo://multi.py",
        rel_path="multi.py",
        content=code,
        repo="test_repo",
        doc_type="code"
    )

    assert len(points) == 2
    # Verify cached chunk has pre-cached vector
    p1 = next(p for p in points if p.text == chunk1)
    p2 = next(p for p in points if p.text == chunk2)

    assert p1.dense_vector == dummy_dense1
    assert p2.dense_vector is not None
    assert p2.dense_vector != dummy_dense1

    # Verify second chunk is now stored in cache
    hash2 = compute_text_hash(chunk2)
    cached = get_cached_embeddings_batch([hash2], model_name=DENSE_MODEL_NAME)
    assert hash2 in cached
    assert cached[hash2]["dense"] == p2.dense_vector

def test_process_file_content_doc_caching():
    md = "# System Architecture\n\nThis system uses SQLite and Qdrant."
    points, symbols, summary, rels, routes, calls = process_file_content(
        filepath="test_repo://docs/arch.md",
        rel_path="docs/arch.md",
        content=md,
        repo="test_repo",
        doc_type="doc"
    )
    assert len(points) > 0
    chunk_hash = compute_text_hash(points[0].text)
    cached = get_cached_embeddings_batch([chunk_hash], model_name=DENSE_MODEL_NAME)
    assert chunk_hash in cached
    assert cached[chunk_hash]["dense"] == points[0].dense_vector

def test_process_file_content_file_size_guard():
    # Content exceeding 500KB limit
    huge_content = "a" * (501 * 1024)
    with patch("app.services.indexing.processor.get_hybrid_embeddings_batch") as mock_embed:
        points, symbols, summary, rels, routes, calls = process_file_content(
            filepath="test_repo://huge.js",
            rel_path="huge.js",
            content=huge_content,
            repo="test_repo",
            doc_type="code"
        )
        mock_embed.assert_not_called()

    assert points == []
    assert symbols == []
    assert rels == []
    assert routes == []
    assert calls == []
