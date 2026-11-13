import json
import pytest
from app.mcp.handlers.storage_handlers import handle_manage
from app.mcp.handlers.repo_handlers import handle_list_repositories
from app.services.auth import set_current_auth_context, AuthContext, Role
from app.services.database.engine import get_db_engine, init_db
import app.services.database as db_mod


@pytest.fixture
def db_engine(tmp_path, monkeypatch):
    db_file = str(tmp_path / "test_mcp_storage.db")
    monkeypatch.setenv("CACHE_DB_PATH", db_file)
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", db_file)
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", db_file)
    engine = get_db_engine(f"sqlite:///{db_file}", reset=True)
    init_db(engine=engine)
    return engine


@pytest.mark.asyncio
async def test_manage_local_file_upload_and_read(tmp_path, monkeypatch, db_engine):
    from app.services.local_storage import LocalStorageService
    import app.services.local_storage as ls_mod
    monkeypatch.setattr(ls_mod, "_storage_service", LocalStorageService(storage_root=str(tmp_path)))

    set_current_auth_context(AuthContext(role=Role.EDITOR))
    up_res = await handle_manage(action="upload", file_path="notes/guide.md", content="# Guide\nTest content")
    up_data = json.loads(up_res)
    assert up_data["action"] == "upload"
    assert up_data["status"] == "success"
    assert up_data["file"] == "notes/guide.md"

    read_res = await handle_manage(action="read", file_path="notes/guide.md")
    read_data = json.loads(read_res)
    assert "# Guide" in read_data["content"]
    assert "Test content" in read_data["content"]


@pytest.mark.asyncio
async def test_manage_local_file_replace_and_delete(tmp_path, monkeypatch, db_engine):
    from app.services.local_storage import LocalStorageService
    import app.services.local_storage as ls_mod
    monkeypatch.setattr(ls_mod, "_storage_service", LocalStorageService(storage_root=str(tmp_path)))

    set_current_auth_context(AuthContext(role=Role.EDITOR))
    await handle_manage(action="upload", file_path="notes/doc.md", content="Initial")

    rep_res = await handle_manage(action="replace", file_path="notes/doc.md", content="Updated")
    rep_data = json.loads(rep_res)
    assert rep_data["action"] == "replace"
    assert rep_data["status"] == "success"

    read_res = await handle_manage(action="read", file_path="notes/doc.md")
    assert "Updated" in json.loads(read_res)["content"]

    del_res = await handle_manage(action="delete", file_path="notes/doc.md")
    del_data = json.loads(del_res)
    assert del_data["action"] == "delete"
    assert del_data["status"] == "success"

    read_after_del = await handle_manage(action="read", file_path="notes/doc.md")
    assert "error" in json.loads(read_after_del)


@pytest.mark.asyncio
async def test_manage_local_file_rbac_forbidden():
    set_current_auth_context(AuthContext(role=Role.VIEWER))
    res = await handle_manage(action="upload", file_path="test.md", content="forbidden")
    res_data = json.loads(res)
    assert res_data.get("forbidden") is True or "Forbidden" in res_data.get("error", "")

    del_res = await handle_manage(action="delete", file_path="test.md")
    del_data = json.loads(del_res)
    assert del_data.get("forbidden") is True or "Forbidden" in del_data.get("error", "")

    sync_res = await handle_manage(action="sync_repo", repo="test-repo")
    sync_data = json.loads(sync_res)
    assert sync_data.get("forbidden") is True or "Forbidden" in sync_data.get("error", "")


@pytest.mark.asyncio
async def test_manage_local_file_input_validation(tmp_path, monkeypatch):
    from app.services.local_storage import LocalStorageService
    import app.services.local_storage as ls_mod
    monkeypatch.setattr(ls_mod, "_storage_service", LocalStorageService(storage_root=str(tmp_path)))

    set_current_auth_context(AuthContext(role=Role.EDITOR))
    res = await handle_manage(action="upload", file_path="test.md", content=None)
    assert "'content' parameter is required" in json.loads(res)["error"]

    inv_res = await handle_manage(action="invalid_action", file_path="test.md")
    assert "Unsupported action" in json.loads(inv_res)["error"]


@pytest.mark.asyncio
async def test_list_repositories_summary_and_filters(tmp_path, monkeypatch, db_engine):
    from app.services.local_storage import LocalStorageService
    import app.services.local_storage as ls_mod
    monkeypatch.setattr(ls_mod, "_storage_service", LocalStorageService(storage_root=str(tmp_path)))

    set_current_auth_context(AuthContext(role=Role.VIEWER))
    out = await handle_list_repositories(source_type="all", include_files=False)
    data = json.loads(out)
    assert "git_repositories" in data
    assert "local_paths" in data
    assert "local_storage" in data


@pytest.mark.asyncio
async def test_list_repositories_detailed_with_data(tmp_path, monkeypatch, db_engine):
    from app.services.local_storage import LocalStorageService
    import app.services.local_storage as ls_mod
    storage = LocalStorageService(storage_root=str(tmp_path))
    monkeypatch.setattr(ls_mod, "_storage_service", storage)

    with db_mod.get_db_connection() as conn:
        conn.execute(
            "INSERT INTO git_repositories (name, url, branch, commit_sha, status) VALUES (?, ?, ?, ?, ?)",
            ("mock_repo", "https://github.com/test/repo", "main", "abc1234567", "ready")
        )
        conn.execute(
            "INSERT INTO indexed_paths (path, repo, category, enabled) VALUES (?, ?, ?, 1)",
            ("/local/path", "monitored_repo", "code")
        )
        conn.execute(
            "INSERT INTO indexed_files (filepath, repo, doc_type, language, mtime, hash) VALUES (?, ?, ?, ?, ?, ?)",
            ("/local/path/main.py", "monitored_repo", "code", "python", 12345.0, "dummyhash")
        )
        conn.execute(
            "INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("mock_repo", "app.py", "my_func", "app.my_func", "function", 1, 5, "def my_func():", "python")
        )
        conn.commit()

    storage.save_file_content("sub/guide.md", "# Guide")
    set_current_auth_context(AuthContext(role=Role.VIEWER))

    git_out = json.loads(await handle_list_repositories(source_type="git", include_files=False))
    assert any(r["name"] == "mock_repo" for r in git_out["git_repositories"])
    assert "local_storage" not in git_out

    mon_out = json.loads(await handle_list_repositories(source_type="monitored_path", include_files=False))
    assert any(p["repo"] == "monitored_repo" for p in mon_out["local_paths"])
    assert "git_repositories" not in mon_out

    ls_out = json.loads(await handle_list_repositories(source_type="local_storage", include_files=False))
    assert "local_storage" in ls_out
    assert "sub" in ls_out["local_storage"]["directories"]

    detailed_out = json.loads(await handle_list_repositories(source_type="all", include_files=True, repo="monitored_repo"))
    assert "files" in detailed_out
    assert any(f["repo"] == "monitored_repo" and f["file"] == "/local/path/main.py" for f in detailed_out["files"])


@pytest.mark.asyncio
async def test_tool_registration_default_and_write_gated(monkeypatch):
    from mcp.server.fastmcp import FastMCP
    from mcp.server.transport_security import TransportSecuritySettings
    from app.mcp.tools import register_mcp_tools_and_resources

    monkeypatch.delenv("MCP_ENABLE_WRITE_TOOLS", raising=False)
    default_srv = FastMCP("DefaultToolsTest", transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))
    register_mcp_tools_and_resources(default_srv)
    default_names = {t.name for t in await default_srv.list_tools()}
    assert default_names == {
        "diagnose_issue",
        "execute_script",
        "find_routes",
        "find_symbol",
        "get_architecture",
        "grep_code",
        "list_repositories",
        "read_file",
        "search",
        "trace_path",
    }

    monkeypatch.setenv("MCP_ENABLE_WRITE_TOOLS", "true")
    write_srv = FastMCP("WriteToolsTest", transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))
    register_mcp_tools_and_resources(write_srv)
    write_names = {t.name for t in await write_srv.list_tools()}
    assert "manage" in write_names
    assert len(write_names) == 11
