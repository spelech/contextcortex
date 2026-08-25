import hmac
import hashlib
import json
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from main import app
from app.services.database import init_db, get_db_connection, set_global_webhook_secret

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_test_db():
    init_db()
    with get_db_connection() as conn:
        conn.execute("DELETE FROM git_repositories WHERE name IN ('test-repo', 'test-gitlab', 'test-gitea', 'test-bitbucket', 'disabled-repo')")
        conn.execute(
            "INSERT INTO git_repositories (name, url, branch, commit_sha, auto_sync) VALUES (?, ?, ?, ?, ?)",
            ("test-repo", "https://github.com/example/test-repo.git", "main", "sha-old", 1)
        )
        conn.execute(
            "INSERT INTO git_repositories (name, url, branch, commit_sha, auto_sync) VALUES (?, ?, ?, ?, ?)",
            ("test-gitlab", "https://gitlab.com/example/test-gitlab.git", "main", "sha-old", 1)
        )
        conn.execute(
            "INSERT INTO git_repositories (name, url, branch, commit_sha, auto_sync) VALUES (?, ?, ?, ?, ?)",
            ("test-gitea", "https://gitea.com/example/test-gitea.git", "main", "sha-old", 1)
        )
        conn.execute(
            "INSERT INTO git_repositories (name, url, branch, commit_sha, auto_sync) VALUES (?, ?, ?, ?, ?)",
            ("test-bitbucket", "https://bitbucket.org/example/test-bitbucket.git", "main", "sha-old", 1)
        )
        conn.execute(
            "INSERT INTO git_repositories (name, url, branch, commit_sha, auto_sync) VALUES (?, ?, ?, ?, ?)",
            ("disabled-repo", "https://github.com/example/disabled-repo.git", "main", "sha-old", 0)
        )
        conn.commit()
    set_global_webhook_secret(None)

@patch("app.api.webhooks.sync_single_git_repo")
def test_github_webhook_no_secret(mock_sync):
    set_global_webhook_secret(None)
    payload = {
        "ref": "refs/heads/main",
        "repository": {
            "clone_url": "https://github.com/example/test-repo.git",
            "name": "test-repo"
        }
    }
    headers = {"X-GitHub-Event": "push"}
    res = client.post("/api/webhooks/git", json=payload, headers=headers)
    assert res.status_code == 200
    assert res.json()["status"] == "sync_triggered"
    assert res.json()["repo"] == "test-repo"

@patch("app.api.webhooks.sync_single_git_repo")
def test_github_webhook_with_secret_valid_and_invalid(mock_sync):
    secret = "super-secret-key"
    set_global_webhook_secret(secret)
    payload_dict = {
        "ref": "refs/heads/main",
        "repository": {"clone_url": "https://github.com/example/test-repo.git"}
    }
    raw_body = json.dumps(payload_dict).encode("utf-8")
    valid_sig = "sha256=" + hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

    # Missing signature header
    res_missing = client.post("/api/webhooks/git", content=raw_body, headers={"X-GitHub-Event": "push", "Content-Type": "application/json"})
    assert res_missing.status_code == 401
    assert "Invalid webhook signature" in res_missing.json()["error"]

    # Invalid signature
    res_bad = client.post("/api/webhooks/git", content=raw_body, headers={"X-GitHub-Event": "push", "X-Hub-Signature-256": "sha256=invalid", "Content-Type": "application/json"})
    assert res_bad.status_code == 401

    # Valid signature
    res_good = client.post("/api/webhooks/git", content=raw_body, headers={"X-GitHub-Event": "push", "X-Hub-Signature-256": valid_sig, "Content-Type": "application/json"})
    assert res_good.status_code == 200
    assert res_good.json()["status"] == "sync_triggered"

@patch("app.api.webhooks.sync_single_git_repo")
def test_gitlab_webhook_with_token(mock_sync):
    secret = "gl-secret-token"
    set_global_webhook_secret(secret)
    payload = {
        "ref": "refs/heads/main",
        "project": {
            "git_http_url": "https://gitlab.com/example/test-gitlab.git",
            "name": "test-gitlab"
        }
    }
    # Bad token
    res_bad = client.post("/api/webhooks/git", json=payload, headers={"X-Gitlab-Event": "Push Hook", "X-Gitlab-Token": "wrong-token"})
    assert res_bad.status_code == 401

    # Valid token
    res_good = client.post("/api/webhooks/git", json=payload, headers={"X-Gitlab-Event": "Push Hook", "X-Gitlab-Token": secret})
    assert res_good.status_code == 200
    assert res_good.json()["status"] == "sync_triggered"
    assert res_good.json()["repo"] == "test-gitlab"

@patch("app.api.webhooks.sync_single_git_repo")
def test_gitea_webhook_with_signature(mock_sync):
    secret = "gitea-secret-key"
    set_global_webhook_secret(secret)
    payload_dict = {
        "ref": "refs/heads/main",
        "repository": {
            "clone_url": "https://gitea.com/example/test-gitea.git",
            "name": "test-gitea"
        }
    }
    raw_body = json.dumps(payload_dict).encode("utf-8")
    sig_hex = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

    # Bad signature
    res_bad = client.post("/api/webhooks/git", content=raw_body, headers={"X-Gitea-Event": "push", "X-Gitea-Signature": "invalid_sig", "Content-Type": "application/json"})
    assert res_bad.status_code == 401

    # Valid signature without sha256= prefix (standard Gitea format)
    res_good = client.post("/api/webhooks/git", content=raw_body, headers={"X-Gitea-Event": "push", "X-Gitea-Signature": sig_hex, "Content-Type": "application/json"})
    assert res_good.status_code == 200
    assert res_good.json()["status"] == "sync_triggered"
    assert res_good.json()["repo"] == "test-gitea"

@patch("app.api.webhooks.sync_single_git_repo")
def test_bitbucket_webhook_payload(mock_sync):
    set_global_webhook_secret(None)
    payload = {
        "push": {
            "changes": [
                {
                    "new": {
                        "name": "main",
                        "type": "branch"
                    }
                }
            ]
        },
        "repository": {
            "links": {
                "html": {
                    "href": "https://bitbucket.org/example/test-bitbucket"
                }
            },
            "name": "test-bitbucket"
        }
    }
    headers = {"X-Event-Key": "repo:push"}
    res = client.post("/api/webhooks/git", json=payload, headers=headers)
    assert res.status_code == 200
    assert res.json()["status"] == "sync_triggered"
    assert res.json()["repo"] == "test-bitbucket"

def test_unregistered_repo_ignored():
    set_global_webhook_secret(None)
    payload = {
        "ref": "refs/heads/main",
        "repository": {
            "clone_url": "https://github.com/unknown/unregistered-repo.git"
        }
    }
    res = client.post("/api/webhooks/git", json=payload)
    assert res.status_code == 200
    assert res.json()["status"] == "ignored"
    assert "Repository or branch not registered" in res.json()["message"]

def test_branch_mismatch_ignored():
    set_global_webhook_secret(None)
    payload = {
        "ref": "refs/heads/feature-branch",
        "repository": {
            "clone_url": "https://github.com/example/test-repo.git"
        }
    }
    res = client.post("/api/webhooks/git", json=payload)
    assert res.status_code == 200
    assert res.json()["status"] == "ignored"
    assert "Repository or branch not registered" in res.json()["message"]

def test_auto_sync_disabled_ignored():
    set_global_webhook_secret(None)
    payload = {
        "ref": "refs/heads/main",
        "repository": {
            "clone_url": "https://github.com/example/disabled-repo.git"
        }
    }
    res = client.post("/api/webhooks/git", json=payload)
    assert res.status_code == 200
    assert res.json()["status"] == "ignored"
    assert "Auto-sync disabled" in res.json()["message"]

def test_malformed_json_payload():
    set_global_webhook_secret(None)
    res = client.post("/api/webhooks/git", content=b"invalid json {{", headers={"Content-Type": "application/json"})
    assert res.status_code == 400
    assert "Invalid JSON payload" in res.json()["error"]

def test_missing_repo_url_payload():
    set_global_webhook_secret(None)
    res = client.post("/api/webhooks/git", json={"ref": "refs/heads/main"})
    assert res.status_code == 400
    assert "Could not identify repository URL" in res.json()["error"]

def test_verify_hmac_sha256_helper():
    from app.api.webhooks import verify_hmac_sha256
    body = b"hello world"
    secret = "secret123"
    expected_hex = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    
    assert verify_hmac_sha256(body, f"sha256={expected_hex}", secret) is True
    assert verify_hmac_sha256(body, expected_hex, secret, prefix="") is True
    assert verify_hmac_sha256(body, "sha256=wrong", secret) is False
    assert verify_hmac_sha256(body, None, secret) is False
    assert verify_hmac_sha256(body, "", secret) is False

def test_parse_webhook_payload_helper():
    from app.api.webhooks import parse_webhook_payload
    
    # GitHub format
    gh_payload = {"ref": "refs/heads/master", "repository": {"clone_url": "git@github.com:user/gh-repo.git"}}
    url, branch = parse_webhook_payload(gh_payload, {})
    assert url == "https://github.com/user/gh-repo.git"
    assert branch == "master"

    # GitLab format
    gl_payload = {"ref": "refs/heads/main", "project": {"git_http_url": "https://gitlab.com/user/gl-repo.git"}}
    url, branch = parse_webhook_payload(gl_payload, {})
    assert url == "https://gitlab.com/user/gl-repo.git"
    assert branch == "main"

    # Bitbucket format
    bb_payload = {
        "push": {"changes": [{"new": {"name": "develop"}}]},
        "repository": {"links": {"clone": [{"href": "https://bitbucket.org/user/bb-repo.git"}]}}
    }
    url, branch = parse_webhook_payload(bb_payload, {})
    assert url == "https://bitbucket.org/user/bb-repo.git"
    assert branch == "develop"
