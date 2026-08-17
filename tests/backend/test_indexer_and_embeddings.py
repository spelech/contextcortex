import os
import sqlite3
import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from app.services.indexer import (
    ensure_collection, get_chunk_uuid, extract_keywords_from_text,
    get_dynamic_catalog_description, process_file_content,
    sync_local_paths, run_full_indexing, notify_list_changed,
    trigger_list_changed_notification, active_sessions, indexing_lock
)
import app.services.embeddings as emb_module
from app.services.embeddings import (
    get_dense_embedding, get_dense_embeddings_batch,
    get_sparse_embedding, get_sparse_embeddings_batch,
    get_hybrid_embeddings, get_hybrid_embeddings_batch,
    get_dense_dim, init_embeddings
)
from app.services.db import init_db, get_db_connection

@pytest.fixture
def temp_indexer_db(tmp_path):
    db_file = str(tmp_path / "test_indexer.db")
    with patch("app.services.db.CACHE_DB_PATH", db_file):
        init_db()
        yield db_file

def test_embeddings_generation():
    dim = get_dense_dim()
    assert dim > 0

    dense = get_dense_embedding("test text for dense vector")
    assert isinstance(dense, list)
    assert len(dense) == dim

    sparse = get_sparse_embedding("test text for sparse vector")
    assert sparse is not None

    batch = get_hybrid_embeddings_batch(["first query", "second query"])
    assert len(batch) == 2
    assert "dense" in batch[0]
    assert "sparse" in batch[0]

    single_hybrid = get_hybrid_embeddings("single test")
    assert "dense" in single_hybrid

def test_empty_embeddings_batches():
    assert get_dense_embeddings_batch([]) == []
    assert get_sparse_embeddings_batch([]) == []
    assert get_hybrid_embeddings_batch([]) == []
    assert get_sparse_embedding("") is not None
    
    with patch("app.services.embeddings.get_sparse_embeddings_batch", return_value=[]):
        assert get_sparse_embedding("something") is None

    with patch("app.services.embeddings.get_hybrid_embeddings_batch", return_value=[]):
        assert get_hybrid_embeddings("something") == {}

def test_api_embeddings_mode():
    with patch.object(emb_module, "EMBEDDING_PROVIDER", "api"):
        # Test when _openai_client is None -> raises RuntimeError
        with patch.object(emb_module, "_openai_client", None):
            with pytest.raises(RuntimeError, match="API Embedding client not initialized"):
                get_dense_embeddings_batch(["test api fail"])

        # Test when _openai_client is initialized
        mock_client = MagicMock()
        mock_data_1 = MagicMock()
        mock_data_1.embedding = [0.2] * 384
        mock_resp = MagicMock()
        mock_resp.data = [mock_data_1]
        mock_client.embeddings.create.return_value = mock_resp

        with patch.object(emb_module, "_openai_client", mock_client):
            res = get_dense_embeddings_batch(["test api text"])
            assert len(res) == 1
            assert res[0] == [0.2] * 384

def test_sparse_embeddings_failures():
    # When _sparse_model is None
    with patch.object(emb_module, "_sparse_model", None):
        res = get_sparse_embeddings_batch(["text1", "text2"])
        assert res == [None, None]

    # When _sparse_model.embed throws exception
    mock_sparse = MagicMock()
    mock_sparse.embed.side_effect = Exception("Sparse model crash")
    with patch.object(emb_module, "_sparse_model", mock_sparse):
        res = get_sparse_embeddings_batch(["text1", "text2"])
        assert res == [None, None]

def test_init_embeddings_fallbacks():
    # Local fastembed failure falls back to API
    with patch.object(emb_module, "EMBEDDING_PROVIDER", "local"), \
         patch("fastembed.TextEmbedding", side_effect=Exception("Model weight missing")), \
         patch("openai.OpenAI"):
        init_embeddings()
        assert emb_module.EMBEDDING_PROVIDER == "api"

    # API mode with fastembed sparse failure
    with patch.object(emb_module, "EMBEDDING_PROVIDER", "api"), \
         patch("openai.OpenAI"), \
         patch("fastembed.SparseTextEmbedding", side_effect=Exception("Sparse model missing")):
        init_embeddings()
        assert emb_module._sparse_model is None

    # API mode with OpenAI client init failure
    with patch.object(emb_module, "EMBEDDING_PROVIDER", "api"), \
         patch("openai.OpenAI", side_effect=Exception("OpenAI init failure")):
        init_embeddings()

    # Restore local for other tests
    emb_module.EMBEDDING_PROVIDER = "local"
    init_embeddings()

def test_chunk_uuid_consistency():
    u1 = get_chunk_uuid("repo_a", "src/main.py", 0)
    u2 = get_chunk_uuid("repo_a", "src/main.py", 0)
    u3 = get_chunk_uuid("repo_a", "src/main.py", 1)
    assert u1 == u2
    assert u1 != u3

def test_extract_keywords():
    text = "FastAPI authentication with JWT tokens and Qdrant vector database."
    keywords = extract_keywords_from_text(text, "Auth Guide", ["Setup", "Tokens"], ["security"])
    assert "fastapi" in keywords
    assert "authentication" in keywords
    assert "jwt" in keywords
    assert "tokens" in keywords

def test_ensure_collection():
    # When collection does not exist
    with patch("app.services.indexer.qdrant") as mock_qdrant:
        mock_qdrant.collection_exists.return_value = False
        ensure_collection()
        mock_qdrant.create_collection.assert_called_once()
        mock_qdrant.create_payload_index.assert_called()

def test_ensure_collection_recreate_schemas():
    # Legacy single vector schema
    with patch("app.services.indexer.qdrant") as mock_qdrant:
        mock_info = MagicMock()
        mock_info.config.params.vectors = "legacy_single_vector"
        mock_info.config.params.sparse_vectors = None
        mock_qdrant.collection_exists.side_effect = [True, False]
        mock_qdrant.get_collection.return_value = mock_info

        ensure_collection()
        mock_qdrant.delete_collection.assert_called_once()
        mock_qdrant.create_collection.assert_called_once()

    # Missing sparse vector schema
    with patch("app.services.indexer.qdrant") as mock_qdrant, \
         patch("app.services.indexer.get_dense_dim", return_value=384):
        mock_info = MagicMock()
        mock_dense = MagicMock()
        mock_dense.size = 384
        mock_info.config.params.vectors = {"dense": mock_dense}
        mock_info.config.params.sparse_vectors = None
        mock_qdrant.collection_exists.side_effect = [True, False]
        mock_qdrant.get_collection.return_value = mock_info

        ensure_collection()
        mock_qdrant.delete_collection.assert_called_once()

    # Exception during ensure_collection
    with patch("app.services.indexer.qdrant") as mock_qdrant:
        mock_qdrant.collection_exists.side_effect = Exception("Qdrant unavailable")
        # Should not raise exception
        ensure_collection()

def test_dynamic_catalog_description(temp_indexer_db):
    with get_db_connection() as conn:
        conn.execute("INSERT INTO git_repositories (name, url, branch, status) VALUES ('notes-rag', 'http://url', 'main', 'synced')")
        conn.execute("INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature) VALUES ('notes-rag', 'app.py', 'fn', 'fn', 'function', 1, 10, 'def fn()')")
        conn.execute("INSERT INTO indexed_files (filepath, repo, doc_type) VALUES ('app.py', 'notes-rag', 'code')")
        conn.commit()

    desc = get_dynamic_catalog_description()
    assert "notes-rag" in desc
    assert "Indexed Code Symbols" in desc

def test_dynamic_catalog_description_error():
    with patch("app.services.indexer.get_db_connection", side_effect=RuntimeError("DB query failed")):
        desc = get_dynamic_catalog_description()
        assert "Hybrid semantic & code symbol search" in desc

def test_process_file_content_doc():
    doc_content = "---\ncategory: architecture\ntags: design, system\n---\n# Architecture\n\nThis is a system overview."
    with patch("app.services.indexer.get_hybrid_embeddings_batch") as mock_embed:
        mock_embed.return_value = [{"dense": [0.1] * 384, "sparse": {"indices": [1], "values": [1.0]}}]
        points, symbols, summary = process_file_content(
            filepath="/docs/arch.md",
            rel_path="arch.md",
            content=doc_content,
            repo="docs-repo",
            doc_type="doc"
        )
        assert len(points) >= 1
        assert points[0].payload["category"] == "architecture"
        assert "design" in points[0].payload["tags"]
        assert len(symbols) == 0
        assert summary[0] == "/docs/arch.md"

def test_process_file_content_doc_corrupt_frontmatter():
    doc_content = "---\n[bad frontmatter YAML---\n# Header\nContent"
    points, symbols, summary = process_file_content(
        filepath="/docs/bad.md",
        rel_path="bad.md",
        content=doc_content,
        repo="docs-repo",
        doc_type="doc"
    )
    assert len(points) >= 1

def test_process_file_content_code():
    code_content = "def calculate_hash(content: str) -> str:\n    return 'hash'\n\nclass DataManager:\n    def save(self):\n        pass\n"
    with patch("app.services.indexer.get_hybrid_embeddings_batch") as mock_embed:
        mock_embed.return_value = [{"dense": [0.1] * 384, "sparse": {"indices": [1], "values": [1.0]}}] * 5
        points, symbols, summary = process_file_content(
            filepath="/src/crypto.py",
            rel_path="src/crypto.py",
            content=code_content,
            repo="backend",
            doc_type="code"
        )
        assert len(points) >= 1
        assert len(symbols) >= 1
        names = [s["name"] for s in symbols]
        assert "calculate_hash" in names or "DataManager" in names

def test_sync_local_paths(temp_indexer_db, tmp_path):
    sub = tmp_path / "local_vault"
    sub.mkdir()
    f1 = sub / "notes.md"
    f1.write_text("# Meeting Notes\n\nDiscussion on project architecture.")
    f2 = sub / "main.py"
    f2.write_text("def hello():\n    print('world')\n")
    f_single = tmp_path / "standalone.py"
    f_single.write_text("def single(): pass\n")

    non_rec = tmp_path / "non_rec_dir"
    non_rec.mkdir()
    f_non_rec = non_rec / "entry.py"
    f_non_rec.write_text("def entry(): pass\n")

    with get_db_connection() as conn:
        conn.execute("INSERT INTO indexed_paths (path, type, recursive, enabled, repo, category) VALUES (?, 'directory', 1, 1, 'my-vault', 'notes')", (str(sub),))
        conn.execute("INSERT INTO indexed_paths (path, type, recursive, enabled, repo, category) VALUES (?, 'file', 0, 1, 'single-repo', 'code')", (str(f_single),))
        conn.execute("INSERT INTO indexed_paths (path, type, recursive, enabled, repo, category) VALUES (?, 'directory', 0, 1, 'nonrec-repo', 'code')", (str(non_rec),))
        conn.execute("INSERT INTO indexed_paths (path, type, recursive, enabled, repo, category) VALUES ('/nonexistent/path', 'directory', 1, 1, 'ghost', 'none')")
        conn.commit()

    with patch("app.services.indexer.qdrant") as mock_qdrant, \
         patch("app.services.indexer.get_hybrid_embeddings_batch") as mock_embed:
        mock_embed.return_value = [{"dense": [0.1] * 384, "sparse": {"indices": [1], "values": [1.0]}}] * 5
        mock_qdrant.collection_exists.return_value = True

        sync_local_paths()
        mock_qdrant.upsert.assert_called()

        with get_db_connection() as conn:
            files = conn.execute("SELECT filepath, repo FROM indexed_files").fetchall()
            assert len(files) == 4

        # Second sync_local_paths: all files are cached & mtime unchanged -> skips processing
        sync_local_paths()

def test_sync_local_paths_default_vault_fallback(temp_indexer_db, tmp_path):
    vault_dir = tmp_path / "default_vault"
    vault_dir.mkdir()
    doc = vault_dir / "default_note.md"
    doc.write_text("# Default Note")

    with patch("app.services.indexer.VAULT_PATH", str(vault_dir)), \
         patch("app.services.indexer.qdrant") as mock_qdrant, \
         patch("app.services.indexer.get_hybrid_embeddings_batch", return_value=[{"dense": [0.1]*384, "sparse": None}]):
        mock_qdrant.collection_exists.return_value = True
        sync_local_paths()

def test_sync_local_paths_exceptions(temp_indexer_db, tmp_path):
    sub = tmp_path / "err_vault"
    sub.mkdir()
    f1 = sub / "error.md"
    f1.write_text("# Error note")

    with get_db_connection() as conn:
        conn.execute("INSERT INTO indexed_paths (path, type, recursive, enabled, repo, category) VALUES (?, 'directory', 1, 1, 'err-vault', 'notes')", (str(sub),))
        conn.commit()

    # Process file exception, qdrant delete exception, qdrant upsert exception, sqlite exception
    with patch("app.services.indexer.process_file_content", side_effect=Exception("Process error")), \
         patch("app.services.indexer.qdrant") as mock_qdrant:
        mock_qdrant.delete.side_effect = Exception("Delete error")
        mock_qdrant.upsert.side_effect = Exception("Upsert error")
        sync_local_paths()

def test_run_full_indexing(temp_indexer_db):
    with patch("app.services.indexer.sync_local_paths") as mock_sync_paths, \
         patch("app.services.indexer.ensure_collection") as mock_ensure:
        res = run_full_indexing()
        assert res is True
        mock_ensure.assert_called_once()
        mock_sync_paths.assert_called_once()

def test_run_full_indexing_concurrency():
    indexing_lock.acquire()
    try:
        res = run_full_indexing()
        assert res is False
    finally:
        indexing_lock.release()

@pytest.mark.asyncio
async def test_notify_list_changed_empty():
    active_sessions.clear()
    await notify_list_changed()

@pytest.mark.asyncio
async def test_notify_list_changed_session_error():
    mock_session = AsyncMock()
    mock_session.send_tool_list_changed.side_effect = Exception("Session closed")
    active_sessions.add(mock_session)
    try:
        await notify_list_changed()
    finally:
        active_sessions.clear()

def test_trigger_list_changed_notification():
    import app.services.indexer as idx_module
    mock_loop = MagicMock()
    mock_loop.is_running.return_value = True

    def close_coro(coro, loop):
        coro.close()
        return MagicMock()

    with patch.object(idx_module, "main_event_loop", mock_loop), \
         patch("app.services.indexer.asyncio.run_coroutine_threadsafe", side_effect=close_coro) as mock_threadsafe:
        idx_module.trigger_list_changed_notification()
        mock_threadsafe.assert_called_once()
