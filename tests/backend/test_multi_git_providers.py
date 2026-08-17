import os
import json
import sqlite3
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from main import app
from app.services.git_manager import (
    detect_git_provider, build_authenticated_url, sanitize_url_for_logging, 
    format_git_permalink, get_remote_head_sha, shallow_clone_repo
)
from app.services.db import (
    save_git_host_credential, list_git_host_credentials, get_git_host_credential,
    delete_git_host_credential, get_effective_git_token
)

client = TestClient(app)

@pytest.fixture
def temp_db(tmp_path):
    db_file = str(tmp_path / "multi_provider_test.db")
    with patch("app.services.db.CACHE_DB_PATH", db_file), patch("app.api.routes.CACHE_DB_PATH", db_file):
        from app.services.db import init_db
        init_db()
        yield db_file

def test_detect_git_provider():
    assert detect_git_provider("https://github.com/org/repo.git") == "github"
    assert detect_git_provider("https://gitlab.com/org/repo.git") == "gitlab"
    assert detect_git_provider("https://gitlab.enterprise.corp/team/project.git") == "gitlab"
    assert detect_git_provider("https://gitea.homelab.arpa/user/notes.git") == "gitea"
    assert detect_git_provider("https://forgejo.internal.lan/infra/configs.git") == "gitea"
    assert detect_git_provider("https://bitbucket.org/team/repo.git") == "bitbucket"
    assert detect_git_provider("http://git.lan:3000/custom/repo.git") == "generic"
    assert detect_git_provider("", explicit_provider="gitlab") == "gitlab"
    assert detect_git_provider("https://github.com/org/repo", explicit_provider="generic") == "generic"
    assert detect_git_provider("") == "generic"

def test_build_authenticated_url_multi_provider():
    # GitHub
    gh = build_authenticated_url("https://github.com/owner/repo.git", "ghp_123", provider="github")
    assert gh == "https://x-access-token:ghp_123@github.com/owner/repo.git"

    # GitLab (default user oauth2)
    gl = build_authenticated_url("https://gitlab.company.com/team/project.git", "glpat_456", provider="gitlab")
    assert gl == "https://oauth2:glpat_456@gitlab.company.com/team/project.git"

    # GitLab with custom deploy user
    gl_deploy = build_authenticated_url("https://gitlab.company.com/team/project.git", "glpat_456", username="gitlab-ci-token", provider="gitlab")
    assert gl_deploy == "https://gitlab-ci-token:glpat_456@gitlab.company.com/team/project.git"

    # Gitea
    gt = build_authenticated_url("http://gitea.local:3000/org/repo.git", "gt_token789", provider="gitea")
    assert gt == "http://gt_token789@gitea.local:3000/org/repo.git"

    # Bitbucket
    bb = build_authenticated_url("https://bitbucket.org/owner/repo.git", "bb_token", provider="bitbucket")
    assert bb == "https://x-token-auth:bb_token@bitbucket.org/owner/repo.git"

    # Generic Git HTTP
    gen = build_authenticated_url("http://git.lan/repo.git", "pass123", username="gituser", provider="generic")
    assert gen == "http://gituser:pass123@git.lan/repo.git"

    # No token or username
    none_auth = build_authenticated_url("https://github.com/owner/repo.git", None)
    assert none_auth == "https://github.com/owner/repo.git"

def test_sanitize_url_for_logging_multi_scheme():
    assert sanitize_url_for_logging("https://oauth2:secret@gitlab.corp/repo.git") == "https://***gitlab.corp/repo.git"
    assert sanitize_url_for_logging("http://user:pass@git.lan:3000/repo.git") == "http://***git.lan:3000/repo.git"
    assert sanitize_url_for_logging("https://token@gitea.org/repo.git") == "https://***gitea.org/repo.git"
    assert sanitize_url_for_logging("") == ""

def test_git_host_credentials_vault_crud(temp_db):
    # Save credential
    save_git_host_credential("gitlab.enterprise.corp", "gitlab", "glpat_corp_secret", auth_user="oauth2")
    save_git_host_credential("http://git.lan:3000", "gitea", "gt_secret_key")

    # Get single
    cred = get_git_host_credential("gitlab.enterprise.corp")
    assert cred is not None
    assert cred["provider"] == "gitlab"
    assert cred["auth_token"] == "glpat_corp_secret"

    # List all
    all_creds = list_git_host_credentials()
    assert len(all_creds) == 2

    # Delete
    delete_git_host_credential("gitlab.enterprise.corp")
    assert get_git_host_credential("gitlab.enterprise.corp") is None

def test_effective_git_token_hierarchy(temp_db):
    # 1. Per-repo override
    tok, user, src = get_effective_git_token("https://gitlab.example.com/repo.git", override_token="repo_tok", override_user="custom_user")
    assert tok == "repo_tok"
    assert user == "custom_user"
    assert src == "Repository Override"

    # 2. Host Vault override
    save_git_host_credential("gitlab.internal.lan", "gitlab", "vault_secret_token", auth_user="gitlab-token")
    tok, user, src = get_effective_git_token("https://gitlab.internal.lan/org/project.git")
    assert tok == "vault_secret_token"
    assert user == "gitlab-token"
    assert src == "Host Vault (gitlab.internal.lan)"

    # 3. Global DB setting
    from app.services.db import set_metadata
    set_metadata("gitea_token", "global_gitea_tok")
    tok, user, src = get_effective_git_token("https://gitea.homelab.arpa/org/repo.git")
    assert tok == "global_gitea_tok"
    assert src == "Database (Gitea)"

    # 4. Environment variable
    with patch.dict(os.environ, {"GITLAB_TOKEN": "glpat_env_token"}):
        tok, user, src = get_effective_git_token("https://gitlab.com/org/repo.git")
        assert tok == "glpat_env_token"
        assert src == "Environment Variable (GITLAB_TOKEN)"

def test_host_credentials_api_endpoints(temp_db):
    # Add host credential via API
    res = client.post("/admin/api/settings/hosts", json={
        "host": "gitlab.corp.internal",
        "provider": "gitlab",
        "auth_user": "oauth2",
        "auth_token": "glpat_secret999"
    })
    assert res.status_code == 200
    assert res.json()["status"] == "success"

    # List host credentials via API
    res_list = client.get("/admin/api/settings/hosts")
    assert res_list.status_code == 200
    data = res_list.json()
    assert len(data) >= 1
    assert data[0]["host"] == "gitlab.corp.internal"
    assert data[0]["provider"] == "gitlab"
    assert "glpat_secret999" not in data[0]["masked_token"]

    # Delete host credential via API
    host_id = data[0]["id"]
    res_del = client.delete(f"/admin/api/settings/hosts/{host_id}")
    assert res_del.status_code == 200
    assert res_del.json()["status"] == "success"

def test_multi_token_settings_api(temp_db):
    res = client.post("/admin/api/settings/token", json={
        "github_token": "ghp_updated123",
        "gitlab_token": "glpat_updated456",
        "gitea_token": "gitea_updated789"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert "providers_auth" in data
    assert data["providers_auth"]["github"]["token_source"] == "Database (Github)"
    assert data["providers_auth"]["gitlab"]["token_source"] == "Database (Gitlab)"
    assert data["providers_auth"]["gitea"]["token_source"] == "Database (Gitea)"
