import os
import sqlite3
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from app.services.indexing import (
    sync_single_git_repo, notify_list_changed, trigger_list_changed_notification,
    active_sessions, ensure_collection
)
from app.mcp.tools import handle_catalog_summary
from app.mcp.mcp_server import mcp_server
from app.services.database import init_db, get_db_connection

from app.models.schemas import CloneResult

@pytest.fixture
def temp_edge_db(tmp_path):
    db_file = str(tmp_path / "test_edge.db")
    with patch("app.services.database.CACHE_DB_PATH", db_file):
        init_db()
        yield db_file

def test_sync_single_git_repo_not_found(temp_edge_db):
    # Repo ID does not exist in database
    sync_single_git_repo(99999)

def test_sync_single_git_repo_unchanged_sha(temp_edge_db):
    with get_db_connection() as conn:
        conn.execute("INSERT INTO git_repositories (name, url, branch, commit_sha, status) VALUES ('cached-repo', 'https://github.com/example/repo.git', 'main', 'abcdef123456', 'synced')")
        conn.commit()
        repo_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    with patch("app.services.git_manager.get_remote_head_sha", return_value="abcdef123456"), \
         patch("app.services.git_manager.shallow_clone_repo") as mock_clone:
        sync_single_git_repo(repo_id)
        mock_clone.assert_not_called()

        with get_db_connection() as conn:
            row = conn.execute("SELECT status, last_synced FROM git_repositories WHERE id = ?", (repo_id,)).fetchone()
            assert row["status"] == "synced"
            assert row["last_synced"] is not None

def test_sync_single_git_repo_clone_error(temp_edge_db):
    with get_db_connection() as conn:
        conn.execute("INSERT INTO git_repositories (name, url, branch, commit_sha, status) VALUES ('fail-repo', 'https://github.com/example/fail.git', 'main', 'oldsha', 'pending')")
        conn.commit()
        repo_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    with patch("app.services.git_manager.get_remote_head_sha", return_value="newsha"), \
         patch("app.services.git_manager.shallow_clone_repo", return_value=CloneResult(temp_dir=None, commit_sha=None, error="Authentication failed")):
        sync_single_git_repo(repo_id)

        with get_db_connection() as conn:
            row = conn.execute("SELECT status, last_error FROM git_repositories WHERE id = ?", (repo_id,)).fetchone()
            assert row["status"] == "error"
            assert "Authentication failed" in row["last_error"]

def test_sync_single_git_repo_full_success(temp_edge_db, tmp_path):
    repo_dir = tmp_path / "cloned_repo"
    repo_dir.mkdir()
    code_file = repo_dir / "app.py"
    code_file.write_text("def run():\n    print('run')\n")
    # File to skip (hidden and unsupported extension)
    hidden_file = repo_dir / ".hidden.py"
    hidden_file.write_text("hidden")
    unsupported_file = repo_dir / "data.dat"
    unsupported_file.write_text("data")

    with get_db_connection() as conn:
        conn.execute("INSERT INTO git_repositories (name, url, branch, commit_sha, status) VALUES ('success-repo', 'https://github.com/example/success.git', 'main', 'oldsha', 'pending')")
        conn.commit()
        repo_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    with patch("app.services.git_manager.get_remote_head_sha", return_value="newsha123"), \
         patch("app.services.git_manager.shallow_clone_repo", return_value=CloneResult(temp_dir=str(repo_dir), commit_sha="newsha123", error=None)), \
         patch("app.services.vector_store.get_vector_store") as mock_get_store, \
         patch("app.services.embeddings.get_hybrid_embeddings_batch", return_value=[{"dense": [0.1]*384, "sparse": {"indices": [1], "values": [1.0]}}]), \
         patch("app.services.git_manager.cleanup_repo_dir") as mock_cleanup:
        mock_store = MagicMock()
        mock_get_store.return_value = mock_store
        
        sync_single_git_repo(repo_id)

        mock_store.delete_by_repo.assert_called_once_with("success-repo")
        mock_store.upsert_documents.assert_called_once()
        mock_cleanup.assert_called_once()

        with get_db_connection() as conn:
            row = conn.execute("SELECT status, commit_sha FROM git_repositories WHERE id = ?", (repo_id,)).fetchone()
            assert row["status"] == "synced"
            assert row["commit_sha"] == "newsha123"

            files = conn.execute("SELECT filepath FROM indexed_files WHERE repo = 'success-repo'").fetchall()
            assert len(files) == 1

def test_sync_single_git_repo_file_parse_error(temp_edge_db, tmp_path):
    repo_dir = tmp_path / "cloned_repo_err"
    repo_dir.mkdir()
    code_file = repo_dir / "bad_file.py"
    code_file.write_text("def broken_code(): pass")

    with get_db_connection() as conn:
        conn.execute("INSERT INTO git_repositories (name, url, branch, commit_sha, status) VALUES ('parse-err-repo', 'https://github.com/example/parse.git', 'main', 'oldsha', 'pending')")
        conn.commit()
        repo_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    with patch("app.services.git_manager.get_remote_head_sha", return_value="sha_parse_err"), \
         patch("app.services.git_manager.shallow_clone_repo", return_value=CloneResult(temp_dir=str(repo_dir), commit_sha="sha_parse_err", error=None)), \
         patch("app.services.indexing.processor.process_file_content", side_effect=Exception("AST corrupt")), \
         patch("app.services.vector_store.get_vector_store") as mock_get_store, \
         patch("app.services.git_manager.cleanup_repo_dir") as mock_cleanup:
        mock_store = MagicMock()
        mock_get_store.return_value = mock_store
        
        sync_single_git_repo(repo_id)
        mock_cleanup.assert_called_once()

def test_sync_single_git_repo_qdrant_purge_error(temp_edge_db, tmp_path):
    repo_dir = tmp_path / "cloned_repo_qdrant_err"
    repo_dir.mkdir()
    code_file = repo_dir / "valid.py"
    code_file.write_text("def valid(): pass")

    with get_db_connection() as conn:
        conn.execute("INSERT INTO git_repositories (name, url, branch, commit_sha, status) VALUES ('qdrant-err-repo', 'https://github.com/example/qdrant.git', 'main', 'oldsha', 'pending')")
        conn.commit()
        repo_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    with patch("app.services.git_manager.get_remote_head_sha", return_value="sha_qd_err"), \
         patch("app.services.git_manager.shallow_clone_repo", return_value=CloneResult(temp_dir=str(repo_dir), commit_sha="sha_qd_err", error=None)), \
         patch("app.services.vector_store.get_vector_store") as mock_get_store, \
         patch("app.services.embeddings.get_hybrid_embeddings_batch", return_value=[{"dense": [0.1]*384, "sparse": None}]), \
         patch("app.services.git_manager.cleanup_repo_dir") as mock_cleanup:
        mock_store = MagicMock()
        mock_store.delete_by_repo.side_effect = Exception("Purge vectors failed")
        mock_get_store.return_value = mock_store
        
        sync_single_git_repo(repo_id)
        mock_cleanup.assert_called_once()

def test_sync_single_git_repo_unexpected_exception(temp_edge_db, tmp_path):
    repo_dir = tmp_path / "cloned_fatal"
    repo_dir.mkdir()
    with get_db_connection() as conn:
        conn.execute("INSERT INTO git_repositories (name, url, branch, commit_sha, status) VALUES ('fatal-repo', 'https://github.com/example/fatal.git', 'main', 'oldsha', 'pending')")
        conn.commit()
        repo_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    with patch("app.services.git_manager.get_remote_head_sha", return_value="newsha_fatal"), \
         patch("app.services.git_manager.shallow_clone_repo", return_value=CloneResult(temp_dir=str(repo_dir), commit_sha="newsha_fatal", error=None)), \
         patch("os.walk", side_effect=RuntimeError("Fatal filesystem crash")), \
         patch("app.services.git_manager.cleanup_repo_dir"):
        sync_single_git_repo(repo_id)

        with get_db_connection() as conn:
            row = conn.execute("SELECT status, last_error FROM git_repositories WHERE id = ?", (repo_id,)).fetchone()
            assert row["status"] == "error"
            assert "Fatal filesystem crash" in row["last_error"]

@pytest.mark.asyncio
async def test_notify_list_changed():
    mock_session = AsyncMock()
    active_sessions.add(mock_session)

    try:
        await notify_list_changed()
        mock_session.send_tool_list_changed.assert_called_once()
        mock_session.send_prompt_list_changed.assert_called_once()
        mock_session.send_resource_list_changed.assert_called_once()
    finally:
        active_sessions.clear()

def test_ensure_collection_delegation():
    with patch("app.services.vector_store.get_vector_store") as mock_get_store:
        mock_store = MagicMock()
        mock_store.ensure_collection.return_value = True
        mock_get_store.return_value = mock_store

        assert ensure_collection() is True
        mock_store.ensure_collection.assert_called_once()


@pytest.mark.asyncio
async def test_catalog_summary_truncation(temp_edge_db):
    with get_db_connection() as conn:
        for i in range(50):
            conn.execute("INSERT INTO indexed_files (filepath, repo, doc_type, language) VALUES (?, 'repo', 'doc', 'markdown')", (f"/docs/file_{i}.md",))
        conn.commit()

    md = await handle_catalog_summary()
    assert "**Total Files Indexed:** 50" in md
    assert "...and 10 more files." in md

@pytest.mark.asyncio
async def test_get_prompt_unknown_error(temp_edge_db):
    with pytest.raises(Exception):
        await mcp_server.get_prompt("non_existent_prompt", {})

