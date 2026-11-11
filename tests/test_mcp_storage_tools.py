import json
import pytest
import asyncio
from app.mcp.handlers.storage_handlers import handle_manage_local_file, handle_what_is_ingested
from app.services.auth import set_current_auth_context, AuthContext, Role, ForbiddenError
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
    up_res = await handle_manage_local_file(action="upload", file_path="notes/guide.md", content="# Guide\nTest content")
    up_data = json.loads(up_res)
    assert up_data["action"] == "upload"
    assert up_data["status"] == "success"
    assert up_data["file"] == "notes/guide.md"

    read_res = await handle_manage_local_file(action="read", file_path="notes/guide.md")
    read_data = json.loads(read_res)
    assert "# Guide" in read_data["content"]
    assert "Test content" in read_data["content"]

@pytest.mark.asyncio
async def test_manage_local_file_replace_and_delete(tmp_path, monkeypatch, db_engine):
    from app.services.local_storage import LocalStorageService
    import app.services.local_storage as ls_mod
    monkeypatch.setattr(ls_mod, "_storage_service", LocalStorageService(storage_root=str(tmp_path)))

    set_current_auth_context(AuthContext(role=Role.EDITOR))
    # Upload initial
    await handle_manage_local_file(action="upload", file_path="notes/doc.md", content="Initial")

    # Replace
    rep_res = await handle_manage_local_file(action="replace", file_path="notes/doc.md", content="Updated")
    rep_data = json.loads(rep_res)
    assert rep_data["action"] == "replace"
    assert rep_data["status"] == "success"

    read_res = await handle_manage_local_file(action="read", file_path="notes/doc.md")
    assert "Updated" in json.loads(read_res)["content"]

    # Delete
    del_res = await handle_manage_local_file(action="delete", file_path="notes/doc.md")
    del_data = json.loads(del_res)
    assert del_data["action"] == "delete"
    assert del_data["status"] == "success"

    # Read after delete should return error message
    read_after_del = await handle_manage_local_file(action="read", file_path="notes/doc.md")
    assert "error" in json.loads(read_after_del)

@pytest.mark.asyncio
async def test_manage_local_file_rbac_forbidden():
    set_current_auth_context(AuthContext(role=Role.VIEWER))
    res = await handle_manage_local_file(action="upload", file_path="test.md", content="forbidden")
    res_data = json.loads(res)
    assert res_data.get("forbidden") is True or "Forbidden" in res_data.get("error", "")

    del_res = await handle_manage_local_file(action="delete", file_path="test.md")
    del_data = json.loads(del_res)
    assert del_data.get("forbidden") is True or "Forbidden" in del_data.get("error", "")

@pytest.mark.asyncio
async def test_manage_local_file_input_validation(tmp_path, monkeypatch):
    from app.services.local_storage import LocalStorageService
    import app.services.local_storage as ls_mod
    monkeypatch.setattr(ls_mod, "_storage_service", LocalStorageService(storage_root=str(tmp_path)))

    set_current_auth_context(AuthContext(role=Role.EDITOR))
    # Missing content on upload
    res = await handle_manage_local_file(action="upload", file_path="test.md", content=None)
    assert "'content' parameter is required" in json.loads(res)["error"]

    # Unsupported action
    inv_res = await handle_manage_local_file(action="invalid_action", file_path="test.md")
    assert "Unsupported action" in json.loads(inv_res)["error"]

@pytest.mark.asyncio
async def test_what_is_ingested_summary_and_filters(tmp_path, monkeypatch, db_engine):
    from app.services.local_storage import LocalStorageService
    import app.services.local_storage as ls_mod
    monkeypatch.setattr(ls_mod, "_storage_service", LocalStorageService(storage_root=str(tmp_path)))

    set_current_auth_context(AuthContext(role=Role.VIEWER))
    out = await handle_what_is_ingested(source_type="all", detail_level="summary")
    data = json.loads(out)
    assert "git_repositories" in data
    assert "monitored_paths" in data
    assert "local_storage" in data

@pytest.mark.asyncio
async def test_what_is_ingested_detailed_with_data(tmp_path, monkeypatch, db_engine):
    from app.services.local_storage import LocalStorageService
    import app.services.local_storage as ls_mod
    storage = LocalStorageService(storage_root=str(tmp_path))
    monkeypatch.setattr(ls_mod, "_storage_service", storage)

    # Insert mock records in db
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

    # Upload local file
    storage.save_file_content("sub/guide.md", "# Guide")

    set_current_auth_context(AuthContext(role=Role.VIEWER))

    # Test source_type git
    git_out = json.loads(await handle_what_is_ingested(source_type="git", detail_level="summary"))
    assert any(r["name"] == "mock_repo" for r in git_out["git_repositories"])
    assert "local_storage" not in git_out

    # Test source_type monitored_path
    mon_out = json.loads(await handle_what_is_ingested(source_type="monitored_path", detail_level="summary"))
    assert any(p["repo"] == "monitored_repo" for p in mon_out["monitored_paths"])
    assert "git_repositories" not in mon_out

    # Test source_type local_storage
    ls_out = json.loads(await handle_what_is_ingested(source_type="local_storage", detail_level="summary"))
    assert "local_storage" in ls_out
    assert "sub" in ls_out["local_storage"]["directories"]

    # Test detailed level
    detailed_out = json.loads(await handle_what_is_ingested(source_type="all", detail_level="detailed", repo_name="monitored_repo"))
    assert "files" in detailed_out
    assert any(f["repo"] == "monitored_repo" and f["file"] == "/local/path/main.py" for f in detailed_out["files"])

@pytest.mark.asyncio
async def test_tool_registration():
    from app.mcp.tools import register_mcp_tools_and_resources
    from app.mcp.mcp_server import mcp_server

    server = register_mcp_tools_and_resources(mcp_server)
    tools = {t.name for t in server._tool_manager.list_tools()}
    assert "manage_local_file" in tools
    assert "what_is_ingested" in tools
