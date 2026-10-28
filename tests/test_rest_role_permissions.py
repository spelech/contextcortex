"""
Role-Matrix Regression Tests for ContextCortex REST API Endpoints.
Verifies least-privilege role policies across Anonymous, Viewer, Editor, and Admin principals
when AUTH_ENABLED=true.
"""

import pytest
from httpx import AsyncClient, ASGITransport
from main import app
from app.services.auth.models import Role
from app.services.auth.service import AuthService, get_auth_service
from app.services.auth.key_service import ApiKeyService
from app.services.database.engine import get_db_engine, init_db
import app.services.local_storage as ls_mod
from app.services.local_storage import LocalStorageService


@pytest.fixture(autouse=True)
def isolated_auth_env(tmp_path, monkeypatch):
    """Sets up an isolated database, auth service, and storage root with AUTH_ENABLED=true."""
    db_file = tmp_path / "test_rest_roles.db"
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_RESOURCE_INDICATOR", "https://contextcortex.local")

    engine = get_db_engine(db_url, reset=True)
    init_db(engine=engine)

    key_service = ApiKeyService(engine=engine)
    auth_service = AuthService(
        auth_enabled=True,
        resource_indicator="https://contextcortex.local",
        key_service=key_service,
    )
    get_auth_service(reset=True, auth_enabled=True, key_service=key_service)

    storage_dir = tmp_path / "storage"
    storage_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(ls_mod, "_storage_service", LocalStorageService(storage_root=str(storage_dir)))

    # Bootstrap roles
    admin_key = auth_service.issue_api_key(name="Admin Key", role=Role.ADMIN)
    editor_key = auth_service.issue_api_key(name="Editor Key", role=Role.EDITOR)
    viewer_key = auth_service.issue_api_key(name="Viewer Key", role=Role.VIEWER)

    yield {
        "engine": engine,
        "key_service": key_service,
        "auth_service": auth_service,
        "admin_key": admin_key,
        "editor_key": editor_key,
        "viewer_key": viewer_key,
        "storage_dir": storage_dir,
    }

    from app.services.auth.service import set_current_auth_context
    set_current_auth_context(None)
    monkeypatch.delenv("AUTH_ENABLED", raising=False)
    get_auth_service(reset=True, auth_enabled=False)


@pytest.mark.asyncio
async def test_anonymous_and_invalid_key_requests_denied(isolated_auth_env):
    """Anonymous or invalid/revoked requests receive 401 Unauthorized."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        # Anonymous
        res = await client.post("/admin/api/storage/upload", json={"path": "a.txt", "content": "hello"})
        assert res.status_code == 401
        assert "WWW-Authenticate" in res.headers

        # Invalid token
        res_inv = await client.get("/admin/api/stats", headers={"Authorization": "Bearer cc_live_invalid_key"})
        assert res_inv.status_code == 401

        # Revoked token
        srv = isolated_auth_env["auth_service"]
        revoked_key = srv.issue_api_key(name="Temp Key", role=Role.EDITOR)
        srv.revoke_api_key(revoked_key.id)

        res_rev = await client.post(
            "/admin/api/storage/upload",
            json={"path": "b.txt", "content": "test"},
            headers={"Authorization": f"Bearer {revoked_key.secret_key}"}
        )
        assert res_rev.status_code == 401


@pytest.mark.asyncio
async def test_viewer_role_permissions(isolated_auth_env):
    """Viewer key can read resources but is denied content mutations & administrative settings (403)."""
    viewer_hdr = {"Authorization": f"Bearer {isolated_auth_env['viewer_key'].secret_key}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        # 1. Permitted Viewer Reads -> HTTP 200
        assert (await client.get("/admin/api/stats", headers=viewer_hdr)).status_code == 200
        assert (await client.get("/admin/api/repos", headers=viewer_hdr)).status_code == 200
        assert (await client.get("/admin/api/paths", headers=viewer_hdr)).status_code == 200
        assert (await client.get("/admin/api/ingestion/catalog", headers=viewer_hdr)).status_code == 200
        assert (await client.get("/admin/api/storage/tree", headers=viewer_hdr)).status_code == 200

        # 2. Denied Storage Content Mutations -> HTTP 403
        res_up = await client.post(
            "/admin/api/storage/upload",
            json={"path": "viewer_file.txt", "content": "viewer write attempt"},
            headers=viewer_hdr
        )
        assert res_up.status_code == 403

        res_put = await client.put(
            "/admin/api/storage/file",
            json={"path": "viewer_file.txt", "content": "replace attempt"},
            headers=viewer_hdr
        )
        assert res_put.status_code == 403

        res_del = await client.delete(
            "/admin/api/storage/file?path=viewer_file.txt",
            headers=viewer_hdr
        )
        assert res_del.status_code == 403

        # Verify side effect was blocked (file was not created)
        assert not (isolated_auth_env["storage_dir"] / "viewer_file.txt").exists()

        # 3. Denied Admin Settings -> HTTP 403
        res_sync_cfg = await client.post(
            "/admin/api/settings/auto-sync",
            json={"interval_mins": 45},
            headers=viewer_hdr
        )
        assert res_sync_cfg.status_code == 403

        assert (await client.get("/admin/api/settings/hosts", headers=viewer_hdr)).status_code == 403
        assert (await client.get("/admin/api/settings/auto-sync", headers=viewer_hdr)).status_code == 403
        assert (await client.get("/admin/api/settings/ai-gateway", headers=viewer_hdr)).status_code == 403
        assert (await client.get("/admin/api/settings/embedding", headers=viewer_hdr)).status_code == 403
        assert (await client.get("/admin/api/logs", headers=viewer_hdr)).status_code == 403

        # 4. Denied Repo / Path Configuration -> HTTP 403
        res_repo = await client.post(
            "/admin/api/repos",
            json={"name": "forbidden_repo", "url": "https://github.com/org/repo"},
            headers=viewer_hdr
        )
        assert res_repo.status_code == 403


@pytest.mark.asyncio
async def test_editor_role_permissions(isolated_auth_env):
    """Editor key can perform content mutations and syncs, but is denied administrative settings (403)."""
    editor_hdr = {"Authorization": f"Bearer {isolated_auth_env['editor_key'].secret_key}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        # 1. Permitted Content Writes & Reads -> HTTP 200
        up_res = await client.post(
            "/admin/api/storage/upload",
            json={"path": "editor_doc.txt", "content": "editor content"},
            headers=editor_hdr
        )
        assert up_res.status_code == 200

        read_res = await client.get("/admin/api/storage/file?path=editor_doc.txt", headers=editor_hdr)
        assert read_res.status_code == 200
        assert read_res.json()["content"] == "editor content"

        put_res = await client.put(
            "/admin/api/storage/file",
            json={"path": "editor_doc.txt", "content": "updated content"},
            headers=editor_hdr
        )
        assert put_res.status_code == 200

        del_res = await client.delete("/admin/api/storage/file?path=editor_doc.txt", headers=editor_hdr)
        assert del_res.status_code == 200

        # 2. Denied Admin Settings -> HTTP 403
        assert (await client.get("/admin/api/settings/hosts", headers=editor_hdr)).status_code == 403
        assert (await client.post(
            "/admin/api/settings/auto-sync",
            json={"interval_mins": 60},
            headers=editor_hdr
        )).status_code == 403

        assert (await client.post(
            "/admin/api/repos",
            json={"name": "editor_repo", "url": "https://github.com/org/repo"},
            headers=editor_hdr
        )).status_code == 403


@pytest.mark.asyncio
async def test_admin_role_permissions(isolated_auth_env):
    """Admin key has full permissions across configuration, editor, and viewer endpoints."""
    admin_hdr = {"Authorization": f"Bearer {isolated_auth_env['admin_key'].secret_key}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        # Admin can update auto-sync setting
        save_sync_res = await client.post(
            "/admin/api/settings/auto-sync",
            json={"interval_mins": 120},
            headers=admin_hdr
        )
        assert save_sync_res.status_code == 200
        assert save_sync_res.json()["interval_mins"] == 120

        # Admin can read auto-sync setting
        get_sync_res = await client.get("/admin/api/settings/auto-sync", headers=admin_hdr)
        assert get_sync_res.status_code == 200
        assert get_sync_res.json()["interval_mins"] == 120

        # Admin can upload file
        up_res = await client.post(
            "/admin/api/storage/upload",
            json={"path": "admin_file.txt", "content": "admin content"},
            headers=admin_hdr
        )
        assert up_res.status_code == 200

        # Admin can read stats
        stats_res = await client.get("/admin/api/stats", headers=admin_hdr)
        assert stats_res.status_code == 200
