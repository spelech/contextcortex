import pytest
from fastapi.testclient import TestClient
from main import app
from app.services.db import init_db, get_db_connection, set_global_webhook_secret, set_auto_sync_interval

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    init_db()

def test_repo_auto_sync_toggle_and_settings_endpoints():
    with get_db_connection() as conn:
        conn.execute("DELETE FROM git_repositories WHERE name = 'api-toggle-repo'")
        conn.execute(
            "INSERT INTO git_repositories (name, url, branch, commit_sha, auto_sync) VALUES (?, ?, ?, ?, ?)",
            ("api-toggle-repo", "https://github.com/example/toggle.git", "main", "sha-1", 1)
        )
        repo_id = conn.execute("SELECT id FROM git_repositories WHERE name = 'api-toggle-repo'").fetchone()[0]
        conn.commit()

    # Toggle auto sync to False
    res = client.patch(f"/admin/api/repos/{repo_id}/auto-sync", json={"auto_sync": False})
    assert res.status_code == 200
    assert res.json()["auto_sync"] is False
    assert res.json()["repo_id"] == repo_id
    assert res.json()["status"] == "success"

    # Toggle auto sync to True
    res_true = client.patch(f"/admin/api/repos/{repo_id}/auto-sync", json={"auto_sync": True})
    assert res_true.status_code == 200
    assert res_true.json()["auto_sync"] is True

    # Get settings
    res_get = client.get("/admin/api/settings/auto-sync")
    assert res_get.status_code == 200
    assert "interval_mins" in res_get.json()
    assert "webhook_url" in res_get.json()
    assert res_get.json()["webhook_url"] == "/api/webhooks/git"

    # Post settings
    res_post = client.post("/admin/api/settings/auto-sync", json={"interval_mins": 30, "global_webhook_secret": "new-sec"})
    assert res_post.status_code == 200
    assert res_post.json()["interval_mins"] == 30
    assert res_post.json()["has_global_secret"] is True

def test_repo_auto_sync_toggle_not_found():
    res = client.patch("/admin/api/repos/999999/auto-sync", json={"auto_sync": False})
    assert res.status_code == 404
    assert "not found" in res.json()["error"].lower()

def test_settings_auto_sync_empty_secret():
    # Setting empty or None secret
    res_post = client.post("/admin/api/settings/auto-sync", json={"interval_mins": 10, "global_webhook_secret": ""})
    assert res_post.status_code == 200
    assert res_post.json()["interval_mins"] == 10
    assert res_post.json()["has_global_secret"] is False

    res_get = client.get("/admin/api/settings/auto-sync")
    assert res_get.status_code == 200
    assert res_get.json()["interval_mins"] == 10
    assert res_get.json()["has_global_secret"] is False

def test_get_repos_includes_auto_sync_and_webhook():
    with get_db_connection() as conn:
        conn.execute("DELETE FROM git_repositories WHERE name = 'api-fields-repo'")
        conn.execute(
            "INSERT INTO git_repositories (name, url, branch, commit_sha, auto_sync, webhook_secret) VALUES (?, ?, ?, ?, ?, ?)",
            ("api-fields-repo", "https://github.com/example/fields.git", "main", "sha-f", 1, "sec-abc")
        )
        conn.commit()

    res = client.get("/admin/api/repos")
    assert res.status_code == 200
    repos = res.json()
    matched = [r for r in repos if r["name"] == "api-fields-repo"]
    assert len(matched) == 1
    assert "auto_sync" in matched[0]
    assert "webhook_secret" in matched[0]
    assert matched[0]["auto_sync"] in (1, True)
    assert matched[0]["webhook_secret"] == "sec-abc"

def test_add_repo_with_auto_sync_and_webhook_secret(monkeypatch):
    monkeypatch.setattr("app.api.routes.sync_single_git_repo", lambda repo_id: None)
    with get_db_connection() as conn:
        conn.execute("DELETE FROM git_repositories WHERE name = 'api-add-custom'")
        conn.commit()

    res = client.post("/admin/api/repos", json={
        "name": "api-add-custom",
        "url": "https://github.com/example/api-add-custom.git",
        "branch": "main",
        "auto_sync": False,
        "webhook_secret": "custom-secret-999"
    })
    assert res.status_code == 200

    res_get = client.get("/admin/api/repos")
    assert res_get.status_code == 200
    matched = [r for r in res_get.json() if r["name"] == "api-add-custom"]
    assert len(matched) == 1
    assert matched[0]["auto_sync"] == 0
    assert matched[0]["webhook_secret"] == "custom-secret-999"

def test_settings_auto_sync_omitted_secret():
    # First set a secret
    client.post("/admin/api/settings/auto-sync", json={"interval_mins": 20, "global_webhook_secret": "preserved-secret"})
    res_get = client.get("/admin/api/settings/auto-sync")
    assert res_get.json()["has_global_secret"] is True
    assert res_get.json()["interval_mins"] == 20

    # Post new interval without secret field (None)
    res_post = client.post("/admin/api/settings/auto-sync", json={"interval_mins": 45})
    assert res_post.status_code == 200
    assert res_post.json()["interval_mins"] == 45
    assert res_post.json()["has_global_secret"] is True

def test_api_error_handling(monkeypatch):
    def mock_db_error(*args, **kwargs):
        raise RuntimeError("Simulated database failure")

    monkeypatch.setattr("app.services.db.set_repo_auto_sync", mock_db_error)
    res_patch = client.patch("/admin/api/repos/1/auto-sync", json={"auto_sync": True})
    assert res_patch.status_code == 500
    assert "Simulated database failure" in res_patch.json()["error"]

    monkeypatch.setattr("app.services.db.get_auto_sync_interval", mock_db_error)
    res_get_settings = client.get("/admin/api/settings/auto-sync")
    assert res_get_settings.status_code == 500
    assert "Simulated database failure" in res_get_settings.json()["error"]

    monkeypatch.setattr("app.services.db.set_auto_sync_interval", mock_db_error)
    res_post_settings = client.post("/admin/api/settings/auto-sync", json={"interval_mins": 15})
    assert res_post_settings.status_code == 500
    assert "Simulated database failure" in res_post_settings.json()["error"]

