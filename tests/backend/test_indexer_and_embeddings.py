import os
import sqlite3
import pytest
from unittest.mock import patch, MagicMock
from app.services.indexer import (
    ensure_collection, get_chunk_uuid, extract_keywords_from_text,
    get_dynamic_catalog_description, process_file_content,
    sync_local_paths, run_full_indexing
)
from app.services.embeddings import (
    get_dense_embedding, get_sparse_embedding, get_hybrid_embeddings_batch, get_dense_dim
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
    with patch("app.services.indexer.qdrant") as mock_qdrant:
        mock_qdrant.collection_exists.return_value = False
        ensure_collection()
        mock_qdrant.create_collection.assert_called_once()
        mock_qdrant.create_payload_index.assert_called()

def test_dynamic_catalog_description(temp_indexer_db):
    with get_db_connection() as conn:
        conn.execute("INSERT INTO git_repositories (name, url, branch, status) VALUES ('notes-rag', 'http://url', 'main', 'synced')")
        conn.execute("INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature) VALUES ('notes-rag', 'app.py', 'fn', 'fn', 'function', 1, 10, 'def fn()')")
        conn.execute("INSERT INTO indexed_files (filepath, repo, doc_type) VALUES ('app.py', 'notes-rag', 'code')")
        conn.commit()

    desc = get_dynamic_catalog_description()
    assert "notes-rag" in desc
    assert "Indexed Code Symbols" in desc

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

    with get_db_connection() as conn:
        conn.execute("INSERT INTO indexed_paths (path, type, recursive, enabled, repo, category) VALUES (?, 'directory', 1, 1, 'my-vault', 'notes')", (str(sub),))
        conn.commit()

    with patch("app.services.indexer.qdrant") as mock_qdrant, \
         patch("app.services.indexer.get_hybrid_embeddings_batch") as mock_embed:
        mock_embed.return_value = [{"dense": [0.1] * 384, "sparse": {"indices": [1], "values": [1.0]}}] * 5
        mock_qdrant.collection_exists.return_value = True

        sync_local_paths()
        mock_qdrant.upsert.assert_called()

        with get_db_connection() as conn:
            files = conn.execute("SELECT filepath, repo FROM indexed_files WHERE repo = 'my-vault'").fetchall()
            assert len(files) == 2

def test_run_full_indexing(temp_indexer_db):
    with patch("app.services.indexer.sync_local_paths") as mock_sync_paths, \
         patch("app.services.indexer.ensure_collection") as mock_ensure:
        run_full_indexing()
        mock_ensure.assert_called_once()
        mock_sync_paths.assert_called_once()
