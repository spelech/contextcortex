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
    assert "Successfully uploaded and indexed" in up_res
    assert "notes/guide.md" in up_res

    read_res = await handle_manage_local_file(action="read", file_path="notes/guide.md")
    assert "# Guide" in read_res
    assert "Test content" in read_res

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
    assert "Successfully replaced and indexed" in rep_res

    read_res = await handle_manage_local_file(action="read", file_path="notes/doc.md")
    assert "Updated" in read_res

    # Delete
    del_res = await handle_manage_local_file(action="delete", file_path="notes/doc.md")
    assert "Successfully deleted" in del_res

    # Read after delete should return error message
    read_after_del = await handle_manage_local_file(action="read", file_path="notes/doc.md")
    assert "Error executing manage_local_file" in read_after_del

@pytest.mark.asyncio
async def test_manage_local_file_rbac_forbidden():
    set_current_auth_context(AuthContext(role=Role.VIEWER))
    res = await handle_manage_local_file(action="upload", file_path="test.md", content="forbidden")
    assert "Forbidden" in res or "Permission denied" in res or "Insufficient permissions" in res

    del_res = await handle_manage_local_file(action="delete", file_path="test.md")
    assert "Forbidden" in del_res or "Permission denied" in del_res or "Insufficient permissions" in del_res

@pytest.mark.asyncio
async def test_manage_local_file_input_validation(tmp_path, monkeypatch):
    from app.services.local_storage import LocalStorageService
    import app.services.local_storage as ls_mod
    monkeypatch.setattr(ls_mod, "_storage_service", LocalStorageService(storage_root=str(tmp_path)))

    set_current_auth_context(AuthContext(role=Role.EDITOR))
    # Missing content on upload
    res = await handle_manage_local_file(action="upload", file_path="test.md", content=None)
    assert "Error: 'content' parameter is required" in res

    # Unsupported action
    inv_res = await handle_manage_local_file(action="invalid_action", file_path="test.md")
    assert "Unsupported action" in inv_res

@pytest.mark.asyncio
async def test_what_is_ingested_summary_and_filters(tmp_path, monkeypatch, db_engine):
    from app.services.local_storage import LocalStorageService
    import app.services.local_storage as ls_mod
    monkeypatch.setattr(ls_mod, "_storage_service", LocalStorageService(storage_root=str(tmp_path)))

    set_current_auth_context(AuthContext(role=Role.VIEWER))
    out = await handle_what_is_ingested(source_type="all", detail_level="summary")
    assert "# ContextCortex Ingestion Catalog" in out
    assert "Git Repositories" in out
    assert "Monitored Paths" in out
    assert "Local Storage" in out

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
    git_out = await handle_what_is_ingested(source_type="git", detail_level="summary")
    assert "mock_repo" in git_out
    assert "Local Storage" not in git_out

    # Test source_type monitored_path
    mon_out = await handle_what_is_ingested(source_type="monitored_path", detail_level="summary")
    assert "monitored_repo" in mon_out
    assert "Git Repositories" not in mon_out

    # Test source_type local_storage
    ls_out = await handle_what_is_ingested(source_type="local_storage", detail_level="summary")
    assert "Local Storage (Uploaded Files)" in ls_out
    assert "**Subdirectories**: sub" in ls_out

    # Test detailed level
    detailed_out = await handle_what_is_ingested(source_type="all", detail_level="detailed", repo_name="monitored_repo")
    assert "Ingested File Details" in detailed_out
    assert "[monitored_repo]" in detailed_out
    assert "/local/path/main.py" in detailed_out

@pytest.mark.asyncio
async def test_tool_registration():
    from app.mcp.tools import register_mcp_tools_and_resources
    from app.mcp.mcp_server import mcp_server

    server = register_mcp_tools_and_resources(mcp_server)
    tools = {t.name for t in server._tool_manager.list_tools()}
    assert "manage_local_file" in tools
    assert "what_is_ingested" in tools
