import pytest
from app.services.database import (
    init_db, get_db_connection, set_repo_auto_sync, 
    get_auto_sync_interval, set_auto_sync_interval,
    get_global_webhook_secret, set_global_webhook_secret,
    list_auto_sync_repos, set_metadata
)

def test_db_migration_and_auto_sync_helpers(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_rag.db")
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", test_db)
    init_db()
    with get_db_connection() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(git_repositories)").fetchall()]
        assert "auto_sync" in cols
        assert "webhook_secret" in cols

    # Test auto sync interval metadata
    assert get_auto_sync_interval() == 15
    set_auto_sync_interval(30)
    assert get_auto_sync_interval() == 30

    # Test global webhook secret metadata
    assert get_global_webhook_secret() is None
    set_global_webhook_secret("my-secret-123")
    assert get_global_webhook_secret() == "my-secret-123"
    set_global_webhook_secret(None)
    assert get_global_webhook_secret() is None


def test_repo_auto_sync_and_list(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_rag2.db")
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", test_db)
    init_db()

    with get_db_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO git_repositories (name, url, branch, provider, auto_sync, webhook_secret) VALUES (?, ?, ?, ?, ?, ?)",
            ("repo1", "https://github.com/org/repo1.git", "main", "github", 1, "sec1")
        )
        repo1_id = cursor.lastrowid
        cursor2 = conn.execute(
            "INSERT INTO git_repositories (name, url, branch, provider, auto_sync, webhook_secret) VALUES (?, ?, ?, ?, ?, ?)",
            ("repo2", "https://github.com/org/repo2.git", "main", "github", 0, None)
        )
        repo2_id = cursor2.lastrowid
        conn.commit()

    auto_repos = list_auto_sync_repos()
    assert len(auto_repos) == 1
    assert auto_repos[0]["id"] == repo1_id
    assert auto_repos[0]["name"] == "repo1"
    assert auto_repos[0]["webhook_secret"] == "sec1"

    # Toggle repo1 to false
    res = set_repo_auto_sync(repo1_id, False)
    assert res is True
    assert len(list_auto_sync_repos()) == 0

    # Toggle repo2 to true
    res2 = set_repo_auto_sync(repo2_id, True)
    assert res2 is True
    auto_repos_after = list_auto_sync_repos()
    assert len(auto_repos_after) == 1
    assert auto_repos_after[0]["id"] == repo2_id

    # Non-existent repo
    assert set_repo_auto_sync(99999, True) is False


def test_auto_sync_interval_edge_cases(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_rag3.db")
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", test_db)
    init_db()

    set_auto_sync_interval(-10)
    assert get_auto_sync_interval() == 0

    set_metadata("auto_sync_interval_mins", "not-a-number")
    assert get_auto_sync_interval() == 15
