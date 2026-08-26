import os
import sqlite3
import pytest
import asyncio
import unittest.mock
from unittest.mock import patch, MagicMock, AsyncMock, mock_open
from app.services.indexing import (
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
from app.services.database import init_db, get_db_connection

@pytest.fixture
def temp_indexer_db(tmp_path):
    db_file = str(tmp_path / "test_indexer.db")
    with patch("app.services.database.CACHE_DB_PATH", db_file):
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
    with patch("app.services.vector_store.get_vector_store") as mock_get_store:
        mock_store = MagicMock()
        mock_store.ensure_collection.return_value = True
        mock_get_store.return_value = mock_store
        res = ensure_collection()
        assert res is True
        mock_store.ensure_collection.assert_called_once()

def test_ensure_collection_failure():
    with patch("app.services.vector_store.get_vector_store") as mock_get_store:
        mock_store = MagicMock()
        mock_store.ensure_collection.side_effect = Exception("Vector store connection error")
        mock_get_store.return_value = mock_store
        res = ensure_collection()
        assert res is False


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
    with patch("app.services.database.get_db_connection", side_effect=RuntimeError("DB query failed")):
        desc = get_dynamic_catalog_description()
        assert "Hybrid semantic & code symbol search" in desc

def test_process_file_content_doc():
    doc_content = "---\ncategory: architecture\ntags: design, system\n---\n# Architecture\n\nThis is a system overview."
    with patch("app.services.embeddings.get_hybrid_embeddings_batch") as mock_embed:
        mock_embed.return_value = [{"dense": [0.1] * 384, "sparse": {"indices": [1], "values": [1.0]}}]
        points, symbols, summary, *extras = process_file_content(
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
    points, symbols, summary, *extras = process_file_content(
        filepath="/docs/bad.md",
        rel_path="bad.md",
        content=doc_content,
        repo="docs-repo",
        doc_type="doc"
    )
    assert len(points) >= 1

def test_process_file_content_code():
    code_content = "def calculate_hash(content: str) -> str:\n    return 'hash'\n\nclass DataManager:\n    def save(self):\n        pass\n"
    with patch("app.services.embeddings.get_hybrid_embeddings_batch") as mock_embed:
        mock_embed.return_value = [{"dense": [0.1] * 384, "sparse": {"indices": [1], "values": [1.0]}}] * 5
        points, symbols, summary, *extras = process_file_content(
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

    with patch("app.services.vector_store.get_vector_store") as mock_get_store, \
         patch("app.services.embeddings.get_hybrid_embeddings_batch") as mock_embed:
        mock_store = MagicMock()
        mock_get_store.return_value = mock_store
        mock_embed.return_value = [{"dense": [0.1] * 384, "sparse": {"indices": [1], "values": [1.0]}}] * 5

        sync_local_paths()
        mock_store.upsert_documents.assert_called()

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

    with patch("app.services.indexing.state.VAULT_PATH", str(vault_dir)), \
         patch("app.services.vector_store.get_vector_store") as mock_get_store, \
         patch("app.services.embeddings.get_hybrid_embeddings_batch", return_value=[{"dense": [0.1]*384, "sparse": None}]):
        mock_store = MagicMock()
        mock_get_store.return_value = mock_store
        sync_local_paths()
        mock_store.upsert_documents.assert_called()

def test_sync_local_paths_exceptions(temp_indexer_db, tmp_path):
    sub = tmp_path / "err_vault"
    sub.mkdir()
    f1 = sub / "error.md"
    f1.write_text("# Error note")

    with get_db_connection() as conn:
        conn.execute("INSERT INTO indexed_paths (path, type, recursive, enabled, repo, category) VALUES (?, 'directory', 1, 1, 'err-vault', 'notes')", (str(sub),))
        conn.commit()

    # Process file exception, store delete exception, store upsert exception, sqlite exception
    with patch("app.services.indexing.processor.process_file_content", side_effect=Exception("Process error")), \
         patch("app.services.vector_store.get_vector_store") as mock_get_store:
        mock_store = MagicMock()
        mock_store.delete_by_path.side_effect = Exception("Delete error")
        mock_store.upsert_documents.side_effect = Exception("Upsert error")
        mock_get_store.return_value = mock_store
        sync_local_paths()

def test_run_full_indexing(temp_indexer_db):
    with patch("app.services.indexing.local_syncer.sync_local_paths") as mock_sync_paths, \
         patch("app.services.indexing.state.ensure_collection") as mock_ensure:
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
    import app.services.indexing as idx_module
    mock_loop = MagicMock()
    mock_loop.is_running.return_value = True

    def close_coro(coro, loop):
        coro.close()
        return MagicMock()

    with patch("app.services.indexing.state.main_event_loop", mock_loop), \
         patch("asyncio.run_coroutine_threadsafe", side_effect=close_coro) as mock_threadsafe:
        idx_module.trigger_list_changed_notification()
        mock_threadsafe.assert_called_once()

def test_detect_system_resources_and_cgroups():
    from app.services.database.connection import detect_system_resources
    res = detect_system_resources()
    assert "cpus" in res
    assert "memory_gb" in res
    assert res["cpus"] >= 1
    assert res["memory_gb"] > 0

    # Test cgroup v2 parsing
    with patch("os.path.exists", side_effect=lambda p: p == "/sys/fs/cgroup/cpu.max"), \
         patch("builtins.open", unittest.mock.mock_open(read_data="200000 100000")):
        cg_res = detect_system_resources()
        assert cg_res["cpus"] == 2

    # Test cgroup v1 parsing
    def cg1_exists(p):
        return p in ("/sys/fs/cgroup/cpu/cpu.cfs_quota_us", "/sys/fs/cgroup/cpu/cpu.cfs_period_us")
    
    def cg1_open(p, *args, **kwargs):
        if "quota" in p:
            return unittest.mock.mock_open(read_data="400000").return_value
        return unittest.mock.mock_open(read_data="100000").return_value

    with patch("os.path.exists", side_effect=cg1_exists), \
         patch("builtins.open", side_effect=cg1_open):
        cg1_res = detect_system_resources()
        assert cg1_res["cpus"] == 4

def test_embedding_db_config_get_set(temp_indexer_db):
    from app.services.database.connection import get_embedding_db_config, set_embedding_db_config
    cfg = get_embedding_db_config()
    assert cfg["provider"] in ("local", "api")
    assert cfg["threads"] >= 1
    assert cfg["batch_size"] >= 1

    set_embedding_db_config(
        provider="local",
        dense_model="test-dense-model",
        sparse_model="test-sparse-model",
        threads=4,
        batch_size=64,
        litellm_url="http://custom:4000/v1",
        litellm_api_key="sk-custom-key"
    )

    updated = get_embedding_db_config()
    assert updated["dense_model"] == "test-dense-model"
    assert updated["sparse_model"] == "test-sparse-model"
    assert updated["threads"] == 4
    assert updated["batch_size"] == 64
    assert updated["litellm_url"] == "http://custom:4000/v1"
    assert updated["litellm_api_key"] == "sk-custom-key"

def test_update_embedding_config(temp_indexer_db):
    from app.services.embeddings import get_embedding_config, update_embedding_config, init_embeddings
    with patch("fastembed.TextEmbedding"), patch("fastembed.SparseTextEmbedding"):
        cfg = update_embedding_config(
            provider="local",
            dense_model="BAAI/bge-small-en-v1.5",
            sparse_model="Qdrant/bm25",
            threads=3,
            batch_size=16
        )
        assert cfg["threads"] == 3
        assert cfg["batch_size"] == 16
        assert cfg["provider"] == "local"

        current = get_embedding_config()
        assert current["threads"] == 3
        assert current["batch_size"] == 16

    # Restore default real embeddings for subsequent tests
    init_embeddings()

