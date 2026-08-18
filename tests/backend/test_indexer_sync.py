import unittest
from unittest.mock import patch, MagicMock
from app.services.db import init_db, get_db_connection
from app.services.indexer import sync_single_git_repo
from app.models.schemas import CloneResult

class TestIndexerSync(unittest.TestCase):

    def setUp(self):
        init_db()
        with get_db_connection() as conn:
            conn.execute("DELETE FROM git_repositories WHERE name = 'test_sync_repo'")
            conn.execute(
                "INSERT INTO git_repositories (name, url, branch, status) VALUES (?, ?, ?, ?)",
                ("test_sync_repo", "https://github.com/test/sync-repo", "main", "pending")
            )
            conn.commit()
            self.repo_id = conn.execute("SELECT id FROM git_repositories WHERE name = 'test_sync_repo'").fetchone()[0]

    def tearDown(self):
        with get_db_connection() as conn:
            conn.execute("DELETE FROM git_repositories WHERE name = 'test_sync_repo'")
            conn.execute("DELETE FROM indexed_files WHERE repo = 'test_sync_repo'")
            conn.commit()

    @patch("app.services.indexer.get_remote_head_sha", return_value="abc12345")
    @patch("app.services.indexer.shallow_clone_repo")
    @patch("app.services.indexer.cleanup_repo_dir")
    def test_sync_single_git_repo_success(self, mock_cleanup, mock_clone, mock_sha):
        mock_clone.return_value = CloneResult(temp_dir="/tmp/mock_repo_dir", commit_sha="abc12345", error=None)

        with patch("os.walk", return_value=[]):
            sync_single_git_repo(self.repo_id)

        with get_db_connection() as conn:
            row = conn.execute("SELECT * FROM git_repositories WHERE id = ?", (self.repo_id,)).fetchone()
            self.assertEqual(row["status"], "synced")
            self.assertEqual(row["commit_sha"], "abc12345")
            self.assertIsNone(row["last_error"])
            self.assertIsNotNone(row["last_synced"])

    @patch("app.services.indexer.get_remote_head_sha", return_value=None)
    @patch("app.services.indexer.shallow_clone_repo")
    @patch("app.services.indexer.cleanup_repo_dir")
    def test_sync_single_git_repo_failure(self, mock_cleanup, mock_clone, mock_sha):
        mock_clone.return_value = CloneResult(temp_dir=None, commit_sha=None, error="Repository not found or authentication required")

        sync_single_git_repo(self.repo_id)

        with get_db_connection() as conn:
            row = conn.execute("SELECT * FROM git_repositories WHERE id = ?", (self.repo_id,)).fetchone()
            self.assertEqual(row["status"], "error")
            self.assertIn("Repository not found", row["last_error"])

    @patch("app.services.indexer.get_remote_head_sha", return_value="abc12345")
    @patch("app.services.indexer.shallow_clone_repo")
    @patch("app.services.indexer.cleanup_repo_dir")
    @patch("app.services.indexer.get_vector_store")
    def test_sync_single_git_repo_vector_upsert_failure(self, mock_get_store, mock_cleanup, mock_clone, mock_sha):
        mock_clone.return_value = CloneResult(temp_dir="/tmp/mock_repo_dir", commit_sha="abc12345", error=None)
        mock_store = MagicMock()
        mock_store.upsert_documents.return_value = False
        mock_get_store.return_value = mock_store

        mock_file_content = 'print("hello world")'
        with patch("os.walk", return_value=[("/tmp/mock_repo_dir", [], ["test.py"])]), \
             patch("builtins.open", unittest.mock.mock_open(read_data=mock_file_content)):
            sync_single_git_repo(self.repo_id)

        with get_db_connection() as conn:
            row = conn.execute("SELECT * FROM git_repositories WHERE id = ?", (self.repo_id,)).fetchone()
            self.assertEqual(row["status"], "error")
            self.assertIsNotNone(row["last_error"])
            self.assertIn("vector", row["last_error"].lower())

if __name__ == "__main__":
    unittest.main()
