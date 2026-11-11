import os
import json
import tempfile
import subprocess
import pytest
from app.services.git_manager import extract_recent_commits, shallow_clone_repo, format_git_commit_url
from app.services.database.engine import get_db_engine, init_db
from app.services.database import get_db_connection
import app.services.database.connection as conn_mod
import app.services.database as db_mod
from app.services.indexing.git_syncer import sync_single_git_repo
from app.mcp.handlers.repo_handlers import handle_get_recent_changes
from app.services.auth import set_current_auth_context, AuthContext, Role
from fastapi.testclient import TestClient
from main import app as fastapi_app

def create_sample_git_repo(repo_dir: str, num_commits: int = 5):
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test Committer"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "committer@example.com"], cwd=repo_dir, check=True, capture_output=True)
    
    for i in range(num_commits):
        file_path = os.path.join(repo_dir, f"module_{i}.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(f"# module {i}\ndef func_{i}():\n    pass\n")
        subprocess.run(["git", "add", "."], cwd=repo_dir, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", f"feat(core): add module_{i}\n\nDetailed commit description for module {i}."], cwd=repo_dir, check=True, capture_output=True)

def test_extract_recent_commits_unit(tmp_path):
    repo_dir = str(tmp_path / "test_git_repo")
    os.makedirs(repo_dir)
    create_sample_git_repo(repo_dir, num_commits=4)

    commits = extract_recent_commits(repo_dir, limit=3)
    assert len(commits) == 3
    # Check newest commit first
    assert commits[0]["message"].startswith("feat(core): add module_3")
    assert commits[0]["files_changed"] == ["module_3.py"]
    assert "Test Committer" in commits[0]["author"]
    assert commits[0]["committed_at"] is not None
    assert len(commits[0]["commit_sha"]) == 40

    # Limit 0 or negative
    assert extract_recent_commits(repo_dir, limit=0) == []
    # Non-existent repo
    assert extract_recent_commits(str(tmp_path / "nonexistent"), limit=5) == []

def test_format_git_commit_url():
    gh_url = format_git_commit_url("https://github.com/org/repo.git", "c1234567")
    assert gh_url == "https://github.com/org/repo/commit/c1234567"

    gl_url = format_git_commit_url("https://gitlab.com/org/repo.git", "c1234567", provider="gitlab")
    assert gl_url == "https://gitlab.com/org/repo/-/commit/c1234567"

    bb_url = format_git_commit_url("https://bitbucket.org/org/repo.git", "c1234567", provider="bitbucket")
    assert bb_url == "https://bitbucket.org/org/repo/commits/c1234567"

    gt_url = format_git_commit_url("https://gitea.example.com/org/repo.git", "c1234567", provider="gitea")
    assert gt_url == "https://gitea.example.com/org/repo/commit/c1234567"

def test_sync_single_git_repo_commits_and_pruning(tmp_path, monkeypatch):
    db_file = str(tmp_path / "test_sync.db")
    monkeypatch.setenv("CACHE_DB_PATH", db_file)
    monkeypatch.setattr(conn_mod, "CACHE_DB_PATH", db_file)
    monkeypatch.setattr(db_mod, "CACHE_DB_PATH", db_file)
    engine = get_db_engine(f"sqlite:///{db_file}", reset=True)
    init_db(engine=engine)

    repo_dir = str(tmp_path / "sample_sync_repo")
    os.makedirs(repo_dir)
    create_sample_git_repo(repo_dir, num_commits=6)

    # 1. Register repo with retain_commits_count = 3
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO git_repositories (name, url, branch, retain_commits_count) VALUES (?, ?, ?, ?)",
            ("sync-repo-test", repo_dir, "master", 3)
        )
        conn.commit()
        repo_id = cursor.lastrowid

    sync_single_git_repo(repo_id)

    # Verify exactly 3 commits retained
    with get_db_connection() as conn:
        rows = conn.execute("SELECT commit_sha, message FROM git_commits WHERE repo = ?", ("sync-repo-test",)).fetchall()
        assert len(rows) == 3

    # 2. Update retain_commits_count = 0 and sync again
    with get_db_connection() as conn:
        conn.execute("UPDATE git_repositories SET retain_commits_count = 0, commit_sha = NULL WHERE id = ?", (repo_id,))
        conn.commit()

    sync_single_git_repo(repo_id)

    # Verify commits cleared
    with get_db_connection() as conn:
        rows_cleared = conn.execute("SELECT commit_sha FROM git_commits WHERE repo = ?", ("sync-repo-test",)).fetchall()
        assert len(rows_cleared) == 0

@pytest.mark.asyncio
async def test_get_recent_changes_mcp_tool(tmp_path, monkeypatch):
    db_file = str(tmp_path / "test_mcp.db")
    monkeypatch.setenv("CACHE_DB_PATH", db_file)
    monkeypatch.setattr(conn_mod, "CACHE_DB_PATH", db_file)
    monkeypatch.setattr(db_mod, "CACHE_DB_PATH", db_file)
    engine = get_db_engine(f"sqlite:///{db_file}", reset=True)
    init_db(engine=engine)

    set_current_auth_context(AuthContext(role=Role.VIEWER))

    # 1. Test when repo not configured / retain_commits_count == 0
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO git_repositories (name, url, branch, retain_commits_count) VALUES (?, ?, ?, ?)",
            ("zero-retention-repo", "https://github.com/org/zero.git", "main", 0)
        )
        conn.commit()

    resp_zero = await handle_get_recent_changes(repo="zero-retention-repo")
    data_zero = json.loads(resp_zero)
    assert data_zero["repo"] == "zero-retention-repo"
    assert data_zero["retained"] is False
    assert data_zero["retained_limit"] == 0
    assert data_zero["commits"] == []
    assert "Commit history is not retained" in data_zero["message"]

    # 2. Test when repo has retained commits
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO git_repositories (name, url, branch, retain_commits_count) VALUES (?, ?, ?, ?)",
            ("active-repo", "https://github.com/org/active.git", "main", 20)
        )
        conn.execute(
            """INSERT INTO git_commits (repo, commit_sha, author, committed_at, message, files_changed)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("active-repo", "1111222233334444555566667777888899990000", "Alice", "2026-11-10T12:00:00Z", "fix(auth): fix token validation", json.dumps(["app/auth.py", "tests/test_auth.py"]))
        )
        conn.execute(
            """INSERT INTO git_commits (repo, commit_sha, author, committed_at, message, files_changed)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("active-repo", "2222333344445555666677778888999900001111", "Bob", "2026-11-09T10:00:00Z", "feat(db): add user model", json.dumps(["app/models.py"]))
        )
        conn.execute(
            """INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("active-repo", "active-repo://app/auth.py", "validate_token", "app.auth.validate_token", "function", 1, 10, "def validate_token():", "python")
        )
        conn.commit()

    # Query all
    resp_all = await handle_get_recent_changes(repo="active-repo")
    data_all = json.loads(resp_all)
    assert data_all["repo"] == "active-repo"
    assert data_all["retained_limit"] == 20
    assert len(data_all["commits"]) == 2
    assert data_all["commits"][0]["short_sha"] == "1111222"
    assert data_all["commits"][0]["commit_url"] == "https://github.com/org/active/commit/1111222233334444555566667777888899990000"

    # Query filtered by filepath
    resp_fp = await handle_get_recent_changes(repo="active-repo", filepath="app/auth.py")
    data_fp = json.loads(resp_fp)
    assert len(data_fp["commits"]) == 1
    assert data_fp["commits"][0]["sha"] == "1111222233334444555566667777888899990000"
    assert data_fp["filter_filepath"] == "app/auth.py"

    # Query filtered by symbol (resolves to app/auth.py)
    resp_sym = await handle_get_recent_changes(repo="active-repo", symbol="validate_token")
    data_sym = json.loads(resp_sym)
    assert len(data_sym["commits"]) == 1
    assert data_sym["commits"][0]["sha"] == "1111222233334444555566667777888899990000"
    assert data_sym["filter_filepath"] == "app/auth.py"

def test_rest_api_patch_retain_commits(tmp_path, monkeypatch):
    db_file = str(tmp_path / "test_api.db")
    monkeypatch.setenv("CACHE_DB_PATH", db_file)
    monkeypatch.setattr(conn_mod, "CACHE_DB_PATH", db_file)
    monkeypatch.setattr(db_mod, "CACHE_DB_PATH", db_file)
    engine = get_db_engine(f"sqlite:///{db_file}", reset=True)
    init_db(engine=engine)

    client = TestClient(fastapi_app)

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO git_repositories (name, url, retain_commits_count) VALUES (?, ?, ?)",
            ("patch-test-repo", "https://github.com/org/patch.git", 20)
        )
        conn.commit()
        repo_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO git_commits (repo, commit_sha, message) VALUES (?, ?, ?)",
            ("patch-test-repo", "sha-test", "dummy commit")
        )
        conn.commit()

    # PATCH to 10
    patch_res = client.patch(f"/admin/api/repos/{repo_id}/retain-commits", json={"retain_commits_count": 10})
    assert patch_res.status_code == 200
    assert patch_res.json()["retain_commits_count"] == 10

    # PATCH to 0 -> should delete commits
    patch_res_0 = client.patch(f"/admin/api/repos/{repo_id}/retain-commits", json={"retain_commits_count": 0})
    assert patch_res_0.status_code == 200
    assert patch_res_0.json()["retain_commits_count"] == 0

    with get_db_connection() as conn:
        commits = conn.execute("SELECT * FROM git_commits WHERE repo = ?", ("patch-test-repo",)).fetchall()
        assert len(commits) == 0

    # 404 on non-existent repo
    patch_res_404 = client.patch("/admin/api/repos/999999/retain-commits", json={"retain_commits_count": 5})
    assert patch_res_404.status_code == 404
