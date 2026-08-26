import os
import hashlib
from unittest.mock import MagicMock, patch
import pytest
from app.services.database.connection import init_db, get_db_connection
from app.services.indexing.git_syncer import compute_git_repo_delta, sync_single_git_repo
from app.models.schemas import CloneResult


@pytest.fixture(autouse=True)
def setup_db(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_delta.db")
    monkeypatch.setenv("CACHE_DB_PATH", test_db)
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", test_db)
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", test_db)
    init_db()


def test_compute_git_repo_delta(tmp_path):
    repo_dir = tmp_path / "cloned_repo"
    repo_dir.mkdir()
    
    # 1. Modified file (hash mismatch)
    (repo_dir / "file1.py").write_text("print('v2')")
    
    # 2. Added file (not in DB)
    (repo_dir / "file2.py").write_text("print('v2')")
    
    # 3. Unchanged file (hash matches)
    (repo_dir / "file3.py").write_text("print('v3_content')")
    hash_file3 = hashlib.sha256(b"print('v3_content')").hexdigest()
    
    # 4. Ignored files/folders
    (repo_dir / ".hidden.py").write_text("print('hidden')")
    node_dir = repo_dir / "node_modules"
    node_dir.mkdir()
    (node_dir / "ignored.py").write_text("print('ignored')")
    (repo_dir / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO indexed_files (filepath, repo, doc_type, hash) VALUES (?, ?, ?, ?)",
            ("test_repo://file1.py", "test_repo", "code", "old_hash_file1")
        )
        conn.execute(
            "INSERT INTO indexed_files (filepath, repo, doc_type, hash) VALUES (?, ?, ?, ?)",
            ("test_repo://file3.py", "test_repo", "code", hash_file3)
        )
        conn.execute(
            "INSERT INTO indexed_files (filepath, repo, doc_type, hash) VALUES (?, ?, ?, ?)",
            ("test_repo://file_deleted.py", "test_repo", "code", "old_hash_deleted")
        )
        # Another repo's file in DB (should NOT be deleted for test_repo)
        conn.execute(
            "INSERT INTO indexed_files (filepath, repo, doc_type, hash) VALUES (?, ?, ?, ?)",
            ("other_repo://other.py", "other_repo", "code", "other_hash")
        )
        conn.commit()

    added, modified, deleted, unchanged = compute_git_repo_delta(str(repo_dir), "test_repo")
    
    added_rel = [os.path.relpath(f, str(repo_dir)) for f in added]
    modified_rel = [os.path.relpath(f, str(repo_dir)) for f in modified]
    unchanged_rel = [os.path.relpath(f, str(repo_dir)) for f in unchanged]

    assert "file2.py" in added_rel
    assert "file1.py" in modified_rel
    assert "file3.py" in unchanged_rel
    assert "test_repo://file_deleted.py" in deleted
    assert "other_repo://other.py" not in deleted
    assert ".hidden.py" not in added_rel
    assert "node_modules/ignored.py" not in added_rel
    assert "image.png" not in added_rel


def test_compute_git_repo_delta_custom_extensions(tmp_path):
    repo_dir = tmp_path / "cloned_repo_ext"
    repo_dir.mkdir()
    (repo_dir / "custom.special").write_text("special_content")
    (repo_dir / "regular.py").write_text("regular_code")

    added, modified, deleted, unchanged = compute_git_repo_delta(
        str(repo_dir), 
        "custom_repo", 
        supported_extensions=(".special",)
    )

    added_rel = [os.path.relpath(f, str(repo_dir)) for f in added]
    assert "custom.special" in added_rel
    assert "regular.py" not in added_rel


def test_sync_single_git_repo_noop_on_empty_delta(tmp_path):
    repo_dir = tmp_path / "repo_noop"
    repo_dir.mkdir()
    (repo_dir / "file1.py").write_text("print('unchanged')")
    hash_file1 = hashlib.sha256(b"print('unchanged')").hexdigest()

    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO git_repositories (id, name, url, branch, commit_sha, status)
               VALUES (1, 'mock-repo', 'https://github.com/mock/repo.git', 'main', 'old_commit_sha', 'synced')"""
        )
        conn.execute(
            "INSERT INTO indexed_files (filepath, repo, doc_type, hash) VALUES (?, ?, ?, ?)",
            ("mock-repo://file1.py", "mock-repo", "code", hash_file1)
        )
        conn.commit()

    clone_res = CloneResult(
        temp_dir=str(repo_dir),
        commit_sha="new_commit_sha_12345678",
        error=None
    )

    with patch("app.services.git_manager.get_remote_head_sha", return_value="new_commit_sha_12345678"), \
         patch("app.services.git_manager.shallow_clone_repo", return_value=clone_res), \
         patch("app.services.git_manager.cleanup_repo_dir") as mock_cleanup, \
         patch("app.services.vector_store.get_vector_store") as mock_get_store:
        
        mock_store = MagicMock()
        mock_get_store.return_value = mock_store

        sync_single_git_repo(1)

        mock_cleanup.assert_any_call(str(repo_dir))
        mock_store.delete_by_repo.assert_not_called()
        mock_store.delete_by_path.assert_not_called()
        mock_store.upsert_documents.assert_not_called()

        with get_db_connection() as conn:
            row = conn.execute("SELECT commit_sha, status, last_error FROM git_repositories WHERE id = 1").fetchone()
            assert row["commit_sha"] == "new_commit_sha_12345678"
            assert row["status"] == "synced"
            assert row["last_error"] is None


def test_sync_single_git_repo_incremental_delta(tmp_path):
    repo_dir = tmp_path / "repo_inc"
    repo_dir.mkdir()
    
    # file_unchanged.py: exists in DB with same hash
    (repo_dir / "file_unchanged.py").write_text("def unchanged(): pass")
    unchanged_hash = hashlib.sha256(b"def unchanged(): pass").hexdigest()
    
    # file_mod.py: exists in DB with old hash, now changed
    (repo_dir / "file_mod.py").write_text("def modified_v2(): pass")
    
    # file_add.py: newly added
    (repo_dir / "file_add.py").write_text("def added(): pass")
    
    # file_del.py is in DB but not on disk

    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO git_repositories (id, name, url, branch, commit_sha, status)
               VALUES (2, 'repo-inc', 'https://github.com/mock/repo.git', 'main', 'old_sha', 'synced')"""
        )
        conn.execute(
            "INSERT INTO indexed_files (filepath, repo, doc_type, hash) VALUES (?, ?, ?, ?)",
            ("repo-inc://file_unchanged.py", "repo-inc", "code", unchanged_hash)
        )
        conn.execute(
            "INSERT INTO indexed_files (filepath, repo, doc_type, hash) VALUES (?, ?, ?, ?)",
            ("repo-inc://file_mod.py", "repo-inc", "code", "old_mod_hash")
        )
        conn.execute(
            "INSERT INTO indexed_files (filepath, repo, doc_type, hash) VALUES (?, ?, ?, ?)",
            ("repo-inc://file_del.py", "repo-inc", "code", "old_del_hash")
        )
        conn.execute(
            "INSERT INTO file_summaries (filepath, repo, title) VALUES (?, ?, ?)",
            ("repo-inc://file_del.py", "repo-inc", "Deleted File Summary")
        )
        conn.commit()

    clone_res = CloneResult(
        temp_dir=str(repo_dir),
        commit_sha="new_inc_sha_abcdef",
        error=None
    )

    deleted_paths = []
    mock_store = MagicMock()
    mock_store.delete_by_path.side_effect = lambda p: deleted_paths.append(p)
    mock_store.upsert_documents.return_value = True

    with patch("app.services.git_manager.get_remote_head_sha", return_value="new_inc_sha_abcdef"), \
         patch("app.services.git_manager.shallow_clone_repo", return_value=clone_res), \
         patch("app.services.git_manager.cleanup_repo_dir") as mock_cleanup, \
         patch("app.services.vector_store.get_vector_store", return_value=mock_store):

        sync_single_git_repo(2)

        mock_cleanup.assert_any_call(str(repo_dir))
        mock_store.delete_by_repo.assert_not_called()
        
        # Check that only modified and deleted paths were deleted from vector store
        assert "repo-inc://file_mod.py" in deleted_paths
        assert "repo-inc://file_del.py" in deleted_paths
        assert "repo-inc://file_unchanged.py" not in deleted_paths

        # Check DB state
        with get_db_connection() as conn:
            rows = conn.execute("SELECT filepath, hash FROM indexed_files WHERE repo = 'repo-inc'").fetchall()
            files_map = {r["filepath"]: r["hash"] for r in rows}
            
            assert "repo-inc://file_unchanged.py" in files_map
            assert files_map["repo-inc://file_unchanged.py"] == unchanged_hash
            
            assert "repo-inc://file_mod.py" in files_map
            assert files_map["repo-inc://file_mod.py"] == hashlib.sha256(b"def modified_v2(): pass").hexdigest()
            
            assert "repo-inc://file_add.py" in files_map
            assert files_map["repo-inc://file_add.py"] == hashlib.sha256(b"def added(): pass").hexdigest()
            
            assert "repo-inc://file_del.py" not in files_map

            # Check file_summaries for deleted file
            summary = conn.execute("SELECT * FROM file_summaries WHERE filepath = 'repo-inc://file_del.py'").fetchone()
            assert summary is None


def test_sync_single_git_repo_batching_over_25(tmp_path):
    repo_dir = tmp_path / "repo_batch"
    repo_dir.mkdir()
    
    # Create 30 files to exceed batch size of 25
    for i in range(30):
        (repo_dir / f"module_{i}.py").write_text(f"def func_{i}(): return {i}")

    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO git_repositories (id, name, url, branch, commit_sha, status)
               VALUES (3, 'repo-batch', 'https://github.com/mock/repo.git', 'main', NULL, 'pending')"""
        )
        conn.commit()

    clone_res = CloneResult(
        temp_dir=str(repo_dir),
        commit_sha="batch_sha_12345",
        error=None
    )

    upsert_calls = []
    mock_store = MagicMock()
    mock_store.upsert_documents.side_effect = lambda pts: (upsert_calls.append(len(pts)), True)[1]

    with patch("app.services.git_manager.get_remote_head_sha", return_value="batch_sha_12345"), \
         patch("app.services.git_manager.shallow_clone_repo", return_value=clone_res), \
         patch("app.services.git_manager.cleanup_repo_dir"), \
         patch("app.services.vector_store.get_vector_store", return_value=mock_store):

        sync_single_git_repo(3)

        assert len(upsert_calls) >= 2  # At least 2 batches (25 + 5)
        
        with get_db_connection() as conn:
            count = conn.execute("SELECT count(*) FROM indexed_files WHERE repo = 'repo-batch'").fetchone()[0]
            assert count == 30


def test_sync_single_git_repo_clone_error(tmp_path):
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO git_repositories (id, name, url, branch, commit_sha, status)
               VALUES (4, 'repo-err', 'https://github.com/mock/repo.git', 'main', NULL, 'pending')"""
        )
        conn.commit()

    clone_res = CloneResult(
        temp_dir=None,
        commit_sha=None,
        error="Authentication failed: bad token"
    )

    with patch("app.services.git_manager.get_remote_head_sha", return_value="remote_sha_err"), \
         patch("app.services.git_manager.shallow_clone_repo", return_value=clone_res), \
         patch("app.services.git_manager.cleanup_repo_dir"):

        sync_single_git_repo(4)

        with get_db_connection() as conn:
            row = conn.execute("SELECT status, last_error FROM git_repositories WHERE id = 4").fetchone()
            assert row["status"] == "error"
            assert "Authentication failed" in row["last_error"]
