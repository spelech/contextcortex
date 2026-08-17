import os
import unittest
from unittest.mock import patch, MagicMock
from app.services.git_manager import (
    get_env_token,
    normalize_git_url,
    build_authenticated_url,
    sanitize_url_for_logging,
    mask_token,
    get_remote_head_sha,
    shallow_clone_repo,
    cleanup_repo_dir,
    format_github_permalink,
    check_github_rate_limit
)

class TestGitManager(unittest.TestCase):

    def test_get_env_token(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(get_env_token())
            with patch.dict(os.environ, {"GITHUB_TOKEN": "  ghp_token123  "}):
                self.assertEqual(get_env_token(), "ghp_token123")
            with patch.dict(os.environ, {"GH_TOKEN": "ghp_ghtoken456"}):
                self.assertEqual(get_env_token(), "ghp_ghtoken456")

    def test_normalize_git_url(self):
        # SSH URLs
        self.assertEqual(
            normalize_git_url("git@github.com:octocat/Hello-World.git"),
            "https://github.com/octocat/Hello-World.git"
        )
        self.assertEqual(
            normalize_git_url("git@gitlab.com:group/subgroup/project.git"),
            "https://gitlab.com/group/subgroup/project.git"
        )
        # HTTPS URLs unchanged
        self.assertEqual(
            normalize_git_url("https://github.com/octocat/Hello-World"),
            "https://github.com/octocat/Hello-World"
        )
        # Empty / whitespace
        self.assertEqual(normalize_git_url(""), "")
        self.assertEqual(
            normalize_git_url("  https://github.com/test/repo  "),
            "https://github.com/test/repo"
        )

    def test_build_authenticated_url(self):
        url = "https://github.com/owner/repo.git"
        token = "ghp_1234567890abcdef"
        auth_url = build_authenticated_url(url, token)
        self.assertEqual(auth_url, "https://x-access-token:ghp_1234567890abcdef@github.com/owner/repo.git")

        # Special characters in token (should be URL encoded)
        token_with_special = "token+with/special@chars:123"
        auth_url_special = build_authenticated_url(url, token_with_special)
        self.assertIn("token%2Bwith%2Fspecial%40chars%3A123", auth_url_special)

        # SSH URL input with token should normalize to HTTPS with token
        ssh_url = "git@github.com:owner/repo.git"
        auth_ssh = build_authenticated_url(ssh_url, token)
        self.assertEqual(auth_ssh, "https://x-access-token:ghp_1234567890abcdef@github.com/owner/repo.git")

        # No token
        self.assertEqual(build_authenticated_url(url, None), url)

        # Already authenticated URL stripped and replaced
        existing_auth = "https://old-user:old-pass@github.com/owner/repo.git"
        replaced_auth = build_authenticated_url(existing_auth, token)
        self.assertEqual(replaced_auth, "https://x-access-token:ghp_1234567890abcdef@github.com/owner/repo.git")

    def test_sanitize_url_for_logging(self):
        url = "https://x-access-token:secret12345@github.com/owner/repo.git"
        sanitized = sanitize_url_for_logging(url)
        self.assertNotIn("secret12345", sanitized)
        self.assertEqual(sanitized, "https://***github.com/owner/repo.git")

    def test_mask_token(self):
        self.assertEqual(mask_token(None), "None")
        self.assertEqual(mask_token(""), "None")
        self.assertEqual(mask_token("short"), "****")
        self.assertEqual(mask_token("ghp_1234567890abcdef"), "ghp_...cdef")

    def test_format_github_permalink(self):
        # Empty url
        self.assertIsNone(format_github_permalink("", "commit123", "src/index.ts"))

        # Single line
        link1 = format_github_permalink(
            "https://github.com/org/repo.git",
            "commit123",
            "src/index.ts",
            10
        )
        self.assertEqual(link1, "https://github.com/org/repo/blob/commit123/src/index.ts#L10")

        # Range lines
        link2 = format_github_permalink(
            "https://github.com/org/repo",
            "commit123",
            "src/index.ts",
            10,
            25
        )
        self.assertEqual(link2, "https://github.com/org/repo/blob/commit123/src/index.ts#L10-L25")

        # Non-github/gitlab URLs return None
        self.assertIsNone(format_github_permalink("https://unknown-host.com/repo", "sha", "file.py"))

    @patch("subprocess.run")
    def test_get_remote_head_sha_success(self, mock_run):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "a1b2c3d4e5f6\trefs/heads/main\n"
        mock_run.return_value = mock_proc

        sha = get_remote_head_sha("https://github.com/org/repo", "main")
        self.assertEqual(sha, "a1b2c3d4e5f6")

    @patch("subprocess.run")
    def test_get_remote_head_sha_fallback_head(self, mock_run):
        # First call (refs/heads) returns empty stdout; second call (HEAD) returns SHA
        proc_empty = MagicMock(returncode=0, stdout="")
        proc_head = MagicMock(returncode=0, stdout="fedcba987654\tHEAD\n")
        mock_run.side_effect = [proc_empty, proc_head]

        sha = get_remote_head_sha("https://github.com/org/repo", "non-existent-branch")
        self.assertEqual(sha, "fedcba987654")

    @patch("subprocess.run")
    def test_get_remote_head_sha_failure(self, mock_run):
        mock_proc = MagicMock()
        mock_proc.returncode = 128
        mock_proc.stdout = ""
        mock_proc.stderr = "Repository not found"
        mock_run.return_value = mock_proc

        sha = get_remote_head_sha("https://github.com/org/nonexistent", "main")
        self.assertIsNone(sha)

    @patch("subprocess.run")
    def test_get_remote_head_sha_exception(self, mock_run):
        mock_run.side_effect = RuntimeError("Subprocess execution error")
        sha = get_remote_head_sha("https://github.com/org/repo", "main")
        self.assertIsNone(sha)

    @patch("subprocess.run")
    def test_shallow_clone_repo_success(self, mock_run):
        def side_effect(cmd, **kwargs):
            proc = MagicMock()
            if "rev-parse" in cmd:
                proc.returncode = 0
                proc.stdout = "commit_sha_123456\n"
            else:
                proc.returncode = 0
                proc.stdout = ""
            return proc

        mock_run.side_effect = side_effect

        res = shallow_clone_repo("https://github.com/org/repo", "main", repo_id="99")
        self.assertIsNone(res.error)
        self.assertEqual(res.commit_sha, "commit_sha_123456")
        self.assertTrue(res.temp_dir and os.path.exists(res.temp_dir))

        # Cleanup
        cleanup_repo_dir(res.temp_dir)
        self.assertFalse(os.path.exists(res.temp_dir))

    @patch("subprocess.run")
    def test_shallow_clone_repo_failure(self, mock_run):
        mock_proc = MagicMock()
        mock_proc.returncode = 128
        mock_proc.stdout = ""
        mock_proc.stderr = "fatal: repository not found"
        mock_run.return_value = mock_proc

        res = shallow_clone_repo("https://github.com/org/invalid-repo", "main")
        self.assertIsNone(res.temp_dir)
        self.assertIsNone(res.commit_sha)
        self.assertIn("Clone failed", res.error)

    @patch("subprocess.run")
    def test_shallow_clone_repo_exception(self, mock_run):
        mock_run.side_effect = RuntimeError("Git executable not found")
        res = shallow_clone_repo("https://github.com/org/error-repo", "main")
        self.assertIsNone(res.temp_dir)
        self.assertIsNone(res.commit_sha)
        self.assertIn("Exception during git clone", res.error)

    @patch("shutil.rmtree")
    def test_cleanup_repo_dir_exception(self, mock_rmtree):
        import tempfile
        test_dir = tempfile.mkdtemp(prefix="test_cleanup_fail_")
        try:
            mock_rmtree.side_effect = PermissionError("Permission denied")
            # Should not raise exception
            cleanup_repo_dir(test_dir)
        finally:
            if os.path.exists(test_dir):
                os.rmdir(test_dir)

    @patch("requests.get")
    def test_check_github_rate_limit_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "resources": {
                "core": {
                    "limit": 5000,
                    "remaining": 4990,
                    "reset": 1786940000
                }
            }
        }
        mock_get.return_value = mock_resp

        status = check_github_rate_limit("token123")
        self.assertTrue(status["authenticated"])
        self.assertEqual(status["limit"], 5000)
        self.assertEqual(status["remaining"], 4990)

    @patch("requests.get")
    def test_check_github_rate_limit_non_200(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_get.return_value = mock_resp

        status = check_github_rate_limit(None)
        self.assertFalse(status["authenticated"])
        self.assertEqual(status["status"], "HTTP 403")

    @patch("requests.get")
    def test_check_github_rate_limit_exception(self, mock_get):
        mock_get.side_effect = Exception("Network connection timeout")
        status = check_github_rate_limit("token123")
        self.assertTrue(status["authenticated"])
        self.assertIn("Network connection timeout", status["error"])


if __name__ == "__main__":
    unittest.main()
