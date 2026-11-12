import os
from unittest.mock import patch

import pytest

from app.models.schemas import CloneResult
from app.services.database.connection import get_db_connection, init_db
from app.services.indexing.git_syncer import sync_single_git_repo
from app.services.search import execute_hybrid_search
from app.services.vector_store.manager import (
    VectorStoreManager,
    set_vector_store_db_config,
)


@pytest.fixture(autouse=True)
def setup_pipeline_env(tmp_path, monkeypatch):
    """Isolate database, vector store, and manager singleton for each test."""
    test_db = str(tmp_path / "test_pipeline_batch.db")
    monkeypatch.setenv("CACHE_DB_PATH", test_db)
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", test_db)
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", test_db)

    chroma_storage = str(tmp_path / "chroma_pipeline_batch_data")
    monkeypatch.setenv("CHROMA_STORAGE_PATH", chroma_storage)
    monkeypatch.setenv("VECTOR_STORE_PROVIDER", "chroma")
    monkeypatch.setenv("VECTOR_STORE_MODE", "persistent")
    monkeypatch.setenv("VECTOR_STORE_STORAGE_PATH", chroma_storage)

    init_db()
    set_vector_store_db_config(
        provider="chroma",
        mode="persistent",
        storage_path=chroma_storage,
        url="",
        collection="pipeline_batch_test_coll",
    )
    VectorStoreManager.reset_instance()

    yield {
        "db_path": test_db,
        "chroma_path": chroma_storage,
        "tmp_path": tmp_path,
    }

    VectorStoreManager.reset_instance()


def test_incremental_pipeline_batching_and_large_commit(tmp_path):
    """
    Verifies that incremental sync handles batches exceeding the 25-file batch threshold,
    persisting all records and vector points correctly across multiple flushes.
    """
    repo_dir = tmp_path / "repo_large"
    os.makedirs(repo_dir / "modules", exist_ok=True)

    # Create 32 python files
    for i in range(32):
        (repo_dir / "modules" / f"mod_{i:02d}.py").write_text(
            f'def function_mod_{i:02d}(x: int) -> int:\n'
            f'    """Compute batch result for module {i}."""\n'
            f'    return x + {i}\n',
            encoding="utf-8",
        )

    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO git_repositories (id, name, url, branch, commit_sha, status)
               VALUES (2, 'large-repo', 'https://github.com/mock/large.git', 'main', NULL, 'pending')"""
        )
        conn.commit()

    clone_res = CloneResult(temp_dir=str(repo_dir), commit_sha="sha_large_1", error=None)

    with patch("app.services.git_manager.get_remote_head_sha", return_value="sha_large_1"), \
         patch("app.services.git_manager.shallow_clone_repo", return_value=clone_res), \
         patch("app.services.git_manager.cleanup_repo_dir"):
        sync_single_git_repo(2)

    with get_db_connection() as conn:
        repo_row = conn.execute("SELECT status, commit_sha FROM git_repositories WHERE id = 2").fetchone()
        assert repo_row["status"] == "synced"
        assert repo_row["commit_sha"] == "sha_large_1"

        count = conn.execute("SELECT count(*) FROM indexed_files WHERE repo = 'large-repo'").fetchone()[0]
        assert count == 32

        sym_count = conn.execute("SELECT count(*) FROM ast_symbols WHERE repo = 'large-repo'").fetchone()[0]
        assert sym_count == 32

    # Search across batched files
    search_res = execute_hybrid_search("Compute batch result for module 15", repo="large-repo", limit=5)
    assert len(search_res) > 0
    assert any("mod_15.py" in r.payload.get("path", "") for r in search_res)


def test_incremental_pipeline_clone_error_resilience(tmp_path):
    """
    Verifies that a failure during shallow clone records an error in git_repositories
    and leaves the prior indexed state intact without data loss.
    """
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO git_repositories (id, name, url, branch, commit_sha, status)
               VALUES (3, 'err-repo', 'https://github.com/mock/err.git', 'main', 'sha_prior', 'synced')"""
        )
        conn.execute(
            "INSERT INTO indexed_files (filepath, repo, doc_type, hash) VALUES ('err-repo://file.py', 'err-repo', 'code', 'h1')"
        )
        conn.commit()

    fail_clone = CloneResult(temp_dir=None, commit_sha=None, error="Git remote auth error: token expired")

    with patch("app.services.git_manager.get_remote_head_sha", return_value="sha_new"), \
         patch("app.services.git_manager.shallow_clone_repo", return_value=fail_clone), \
         patch("app.services.git_manager.cleanup_repo_dir"):
        sync_single_git_repo(3)

    with get_db_connection() as conn:
        repo_row = conn.execute("SELECT status, last_error, commit_sha FROM git_repositories WHERE id = 3").fetchone()
        assert repo_row["status"] == "error"
        assert "token expired" in repo_row["last_error"]
        assert repo_row["commit_sha"] == "sha_prior"

        # Verify prior indexed file is preserved
        prior_file = conn.execute("SELECT filepath FROM indexed_files WHERE repo = 'err-repo'").fetchone()
        assert prior_file["filepath"] == "err-repo://file.py"
