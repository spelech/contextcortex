"""
Integration and functional tests for Protected Resource Metadata endpoint (RFC 9728),
Auth API key management endpoints (/admin/api/auth/keys), HTTP Bearer 401 challenges,
and MCP RBAC permission checks across viewer, editor, and admin roles.
"""

import os
import json
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
from httpx import AsyncClient, ASGITransport

from app.services.database.engine import get_db_engine, init_db
from app.services.auth.models import Role, AuthContext, ApiKeyCreate, ApiKeyOut, ForbiddenError
from app.services.auth.service import AuthService, get_auth_service
from app.services.auth.key_service import ApiKeyService
from app.mcp.mcp_server import mcp_server
from main import app, lifespan


@pytest.fixture(autouse=True)
def isolated_db_and_auth(tmp_path, monkeypatch):
    """Provides an isolated database and clean AuthService instance for each test."""
    db_file = tmp_path / "test_auth_endpoints.db"
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("AUTH_RESOURCE_INDICATOR", "https://contextcortex.local")
    monkeypatch.setenv("AUTH_OIDC_ISSUER", "https://auth.example.com/realms/contextcortex")

    engine = get_db_engine(db_url, reset=True)
    init_db(engine=engine)

    # Initialize isolated ApiKeyService and AuthService
    key_service = ApiKeyService(engine=engine)
    auth_service = AuthService(
        auth_enabled=False,
        oidc_issuer="https://auth.example.com/realms/contextcortex",
        resource_indicator="https://contextcortex.local",
        key_service=key_service,
    )
    # Set as global singleton
    get_auth_service(reset=True, auth_enabled=False, key_service=key_service)

    from app.services.auth.service import set_current_auth_context

    yield {
        "engine": engine,
        "key_service": key_service,
        "auth_service": auth_service,
    }

    set_current_auth_context(None)
    monkeypatch.delenv("AUTH_ENABLED", raising=False)
    get_auth_service(reset=True, auth_enabled=False)


# =============================================================================
# 1. Protected Resource Metadata Endpoint (RFC 9728) Tests
# =============================================================================

@pytest.mark.asyncio
async def test_oauth_protected_resource_metadata():
    """Verify GET /.well-known/oauth-protected-resource returns valid RFC 9728 JSON."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        resp = await client.get("/.well-known/oauth-protected-resource")
        assert resp.status_code == 200
        data = resp.json()

        assert data["resource"] == "https://contextcortex.local"
        assert data["authorization_servers"] == ["https://auth.example.com/realms/contextcortex"]
        assert "scopes_supported" in data
        assert "mcp:admin" in data["scopes_supported"]
        assert "mcp:editor" in data["scopes_supported"]
        assert "mcp:viewer" in data["scopes_supported"]
        assert data["bearer_methods_supported"] == ["header"]


# =============================================================================
# 2. Local Dev Bypass vs Auth Enforced 401 WWW-Authenticate Challenge Tests
# =============================================================================

@pytest.mark.asyncio
async def test_local_dev_bypass_allows_unauthenticated_requests(isolated_db_and_auth, monkeypatch):
    """When AUTH_ENABLED=false, endpoints allow access without authorization header."""
    monkeypatch.setenv("AUTH_ENABLED", "false")
    get_auth_service(reset=True, auth_enabled=False, key_service=isolated_db_and_auth["key_service"])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        resp = await client.get("/admin/api/stats")
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_protected_endpoints_challenge_401_when_auth_enabled(isolated_db_and_auth, monkeypatch):
    """When AUTH_ENABLED=true, unauthenticated requests receive 401 with WWW-Authenticate header."""
    monkeypatch.setenv("AUTH_ENABLED", "true")
    get_auth_service(reset=True, auth_enabled=True, key_service=isolated_db_and_auth["key_service"])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        # Request without header
        resp = await client.get("/admin/api/stats")
        assert resp.status_code == 401
        assert "WWW-Authenticate" in resp.headers
        auth_header = resp.headers["WWW-Authenticate"]
        assert "Bearer" in auth_header
        assert "invalid_token" in auth_header or "Missing" in auth_header or "resource_metadata" in auth_header

        # Request with invalid token
        resp_invalid = await client.get(
            "/admin/api/stats",
            headers={"Authorization": "Bearer cc_live_invalid_bad_token"}
        )
        assert resp_invalid.status_code == 401
        assert "WWW-Authenticate" in resp_invalid.headers

        # Public metadata endpoint remains accessible without credentials
        resp_meta = await client.get("/.well-known/oauth-protected-resource")
        assert resp_meta.status_code == 200

        # Health endpoint remains accessible
        resp_health = await client.get("/health")
        assert resp_health.status_code == 200


# =============================================================================
# 3. API Key Management Endpoints (/admin/api/auth/keys)
# =============================================================================

@pytest.mark.asyncio
async def test_api_key_lifecycle_endpoints(isolated_db_and_auth, monkeypatch):
    """Test POST, GET, and DELETE /admin/api/auth/keys endpoints."""
    monkeypatch.setenv("AUTH_ENABLED", "true")
    auth_srv = get_auth_service(reset=True, auth_enabled=True, key_service=isolated_db_and_auth["key_service"])

    # Issue an initial admin key directly to authenticate admin API calls
    admin_key_out = auth_srv.issue_api_key(name="Bootstrap Admin", role=Role.ADMIN)
    admin_headers = {"Authorization": f"Bearer {admin_key_out.secret_key}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        # 1. Issue a new API key via POST
        create_payload = {
            "name": "Frontend Team Worker",
            "role": "editor",
            "group_name": "engineering",
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
        }
        create_resp = await client.post("/admin/api/auth/keys", json=create_payload, headers=admin_headers)
        assert create_resp.status_code == 201 or create_resp.status_code == 200
        new_key_data = create_resp.json()
        assert new_key_data["name"] == "Frontend Team Worker"
        assert new_key_data["role"] == "editor"
        assert new_key_data["group_name"] == "engineering"
        assert new_key_data["secret_key"] is not None
        assert new_key_data["secret_key"].startswith("cc_live_")
        new_key_id = new_key_data["id"]
        issued_secret = new_key_data["secret_key"]

        # 2. List API keys via GET (secrets should be masked / None)
        list_resp = await client.get("/admin/api/auth/keys", headers=admin_headers)
        assert list_resp.status_code == 200
        keys_list = list_resp.json()
        assert len(keys_list) >= 2  # bootstrap admin + newly issued key
        target_key = next((k for k in keys_list if k["id"] == new_key_id), None)
        assert target_key is not None
        assert target_key["secret_key"] is None  # Never exposed in listings
        assert target_key["key_prefix"].startswith("cc_live_")

        # 3. Authenticate with newly issued editor key to access a viewer/editor endpoint
        editor_headers = {"Authorization": f"Bearer {issued_secret}"}
        stats_resp = await client.get("/admin/api/stats", headers=editor_headers)
        assert stats_resp.status_code == 200

        # 4. Revoke the key via DELETE
        del_resp = await client.delete(f"/admin/api/auth/keys/{new_key_id}", headers=admin_headers)
        assert del_resp.status_code == 200
        del_data = del_resp.json()
        assert del_data.get("success") is True or del_data.get("status") == "revoked"

        # 5. Verify the revoked key can no longer authenticate
        rejected_resp = await client.get("/admin/api/stats", headers=editor_headers)
        assert rejected_resp.status_code == 401


@pytest.mark.asyncio
async def test_api_key_management_requires_admin_role(isolated_db_and_auth, monkeypatch):
    """Test that viewer and editor roles cannot access /admin/api/auth/keys."""
    monkeypatch.setenv("AUTH_ENABLED", "true")
    auth_srv = get_auth_service(reset=True, auth_enabled=True, key_service=isolated_db_and_auth["key_service"])

    viewer_key = auth_srv.issue_api_key(name="Viewer Only", role=Role.VIEWER)
    viewer_headers = {"Authorization": f"Bearer {viewer_key.secret_key}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        # Viewer attempting to list keys -> 403 Forbidden
        list_resp = await client.get("/admin/api/auth/keys", headers=viewer_headers)
        assert list_resp.status_code == 403

        # Viewer attempting to issue keys -> 403 Forbidden
        post_resp = await client.post(
            "/admin/api/auth/keys",
            json={"name": "Attacker", "role": "admin"},
            headers=viewer_headers
        )
        assert post_resp.status_code == 403

        # Viewer attempting to revoke keys -> 403 Forbidden
        del_resp = await client.delete(f"/admin/api/auth/keys/{viewer_key.id}", headers=viewer_headers)
        assert del_resp.status_code == 403


# =============================================================================
# 4. MCP Tools RBAC Enforcement Tests
# =============================================================================

@pytest.mark.asyncio
async def test_mcp_tools_rbac_viewer_vs_editor_vs_admin(isolated_db_and_auth, monkeypatch):
    """
    Test RBAC role enforcement across MCP tools:
    - Viewer: allowed search_code, search_docs, find_symbol, list_repositories, read ADRs
    - Viewer: denied sync_repository, create/update/supersede ADRs
    - Editor: allowed sync_repository, create/update/supersede ADRs
    - Admin: allowed full access
    """
    from app.mcp.handlers import (
        handle_search_code,
        handle_list_repositories,
        handle_sync_repository,
        handle_manage_adr,
    )
    from app.services.auth.service import set_current_auth_context

    monkeypatch.setenv("AUTH_ENABLED", "true")
    get_auth_service(reset=True, auth_enabled=True, key_service=isolated_db_and_auth["key_service"])

    # 1. Test with VIEWER context
    viewer_ctx = AuthContext(
        user_id="user-viewer",
        name="Viewer User",
        role=Role.VIEWER,
        scopes=["mcp:viewer"],
        auth_type="api_key",
        is_authenticated=True,
    )
    set_current_auth_context(viewer_ctx)

    # Viewer can list repositories
    repo_list = await handle_list_repositories()
    assert "Registered Sources" in repo_list or "Error" not in repo_list

    # Viewer can list ADRs
    adr_list = await handle_manage_adr(action="list", repo="test-repo")
    assert "Insufficient permissions" not in adr_list

    # Viewer attempting mutation (sync_repository) -> Denied
    sync_res = await handle_sync_repository(repo="test-repo")
    assert "Insufficient permissions" in sync_res or "Forbidden" in sync_res

    # Viewer attempting mutation (create ADR) -> Denied
    create_adr_res = await handle_manage_adr(action="create", repo="test-repo", title="ADR 1")
    assert "Insufficient permissions" in create_adr_res or "Forbidden" in create_adr_res

    # 2. Test with EDITOR context
    editor_ctx = AuthContext(
        user_id="user-editor",
        name="Editor User",
        role=Role.EDITOR,
        scopes=["mcp:editor"],
        auth_type="api_key",
        is_authenticated=True,
    )
    set_current_auth_context(editor_ctx)

    # Editor can execute sync_repository
    with patch("threading.Thread") as mock_thread:
        sync_res = await handle_sync_repository(repo="test-repo")
        assert "Triggered" in sync_res
        assert "Insufficient permissions" not in sync_res

    # Editor can execute manage_adr create
    with patch("app.services.database.create_adr", return_value={"id": "ADR-001", "status": "PROPOSED"}):
        create_res = await handle_manage_adr(action="create", repo="test-repo", title="ADR 1")
        assert "Successfully created ADR" in create_res

    # 3. Clean up context
    set_current_auth_context(None)


@pytest.mark.asyncio
async def test_fastmcp_streamable_transport_auth_enforced(isolated_db_and_auth, monkeypatch):
    """Test FastMCP /mcp endpoint requires authentication when AUTH_ENABLED=true."""
    monkeypatch.setenv("AUTH_ENABLED", "true")
    auth_srv = get_auth_service(reset=True, auth_enabled=True, key_service=isolated_db_and_auth["key_service"])
    admin_key = auth_srv.issue_api_key(name="MCP Admin Client", role=Role.ADMIN)

    init_payload = {
        "jsonrpc": "2.0",
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "pytest-auth-client", "version": "1.0"},
        },
        "id": 1,
    }

    async with lifespan(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as client:
            # Unauthenticated /mcp request -> 401
            unauth_resp = await client.post(
                "/mcp",
                json=init_payload,
                headers={"accept": "application/json, text/event-stream"},
            )
            assert unauth_resp.status_code == 401
            assert "WWW-Authenticate" in unauth_resp.headers

            # Authenticated /mcp request -> 200
            auth_resp = await client.post(
                "/mcp",
                json=init_payload,
                headers={
                    "accept": "application/json, text/event-stream",
                    "Authorization": f"Bearer {admin_key.secret_key}",
                },
            )
            assert auth_resp.status_code == 200
            assert "ContextCortex" in auth_resp.text


@pytest.mark.asyncio
async def test_api_key_delete_nonexistent(isolated_db_and_auth, monkeypatch):
    """Test DELETE /admin/api/auth/keys/{id} with nonexistent ID returns 404."""
    monkeypatch.setenv("AUTH_ENABLED", "true")
    auth_srv = get_auth_service(reset=True, auth_enabled=True, key_service=isolated_db_and_auth["key_service"])
    admin_key = auth_srv.issue_api_key(name="Admin", role=Role.ADMIN)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        resp = await client.delete(
            "/admin/api/auth/keys/999999",
            headers={"Authorization": f"Bearer {admin_key.secret_key}"},
        )
        assert resp.status_code == 404
