import os
import sqlite3
import pytest
from unittest.mock import patch, MagicMock
from app.services.db import (
    init_db, get_db_connection, set_metadata, get_metadata,
    get_effective_github_token, get_token_source, get_default_db_path
)
import app.mcp.tools as tools_module
from app.mcp.tools import (
    execute_tool, read_resource, get_prompt, get_prompts,
    handle_search_code, handle_search_docs, handle_find_symbol,
    handle_get_file_outline, handle_list_repositories, handle_sync_repository,
    handle_index_status, handle_catalog_summary, handle_search_infrastructure_docs,
    handle_find_implementation_symbol, register_mcp_tools_and_resources
)
from mcp.types import TextContent

@pytest.fixture
def temp_db(tmp_path):
    db_file = str(tmp_path / "test_rag.db")
    with patch("app.services.db.CACHE_DB_PATH", db_file):
        init_db()
        yield db_file

def test_db_path_and_init():
    # When CACHE_DB_PATH is in env
    with patch.dict(os.environ, {"CACHE_DB_PATH": "/custom/path/cache.db"}):
        assert get_default_db_path() == "/custom/path/cache.db"

    # When /app is writable
    with patch.dict(os.environ, {}, clear=True), \
         patch("os.path.exists", side_effect=lambda p: p == "/app"), \
         patch("os.access", return_value=True):
        assert get_default_db_path() == "/app/data/index_cache.db"

    # Fallback to local data dir
    with patch.dict(os.environ, {}, clear=True), \
         patch("os.path.exists", return_value=False):
        assert "data/index_cache.db" in get_default_db_path()

def test_db_init_seeding_vault(tmp_path):
    vault_dir = tmp_path / "seed_vault"
    vault_dir.mkdir()
    db_file = str(tmp_path / "test_seed.db")
    with patch("app.services.db.CACHE_DB_PATH", db_file):
        init_db(vault_path=str(vault_dir))
        with sqlite3.connect(db_file) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT path, repo FROM indexed_paths").fetchall()
            assert len(rows) == 1
            assert rows[0]["repo"] == "vault"

def test_db_init_seeding_errors(tmp_path):
    db_file = str(tmp_path / "test_err_seed.db")
    with patch("app.services.db.CACHE_DB_PATH", db_file):
        init_db()
        real_conn = sqlite3.connect(db_file)
        real_conn.row_factory = sqlite3.Row
        mock_conn = MagicMock(wraps=real_conn)
        def failing_execute(query, *args, **kwargs):
            if "SELECT count(*) FROM custom_prompts" in query or "DELETE FROM indexed_paths" in query:
                raise sqlite3.OperationalError("Simulated query failure")
            return real_conn.execute(query, *args, **kwargs)
        mock_conn.execute.side_effect = failing_execute
        mock_conn.__enter__.return_value = mock_conn

        with patch("app.services.db.get_db_connection", return_value=mock_conn):
            init_db(vault_path=str(tmp_path))

def test_db_metadata_errors(temp_db):
    with patch("app.services.db.get_db_connection", side_effect=Exception("DB down")):
        # get_metadata returns default
        assert get_metadata("some_key", "default_val") == "default_val"
        # set_metadata logs error without raising
        set_metadata("some_key", "some_val")

def test_db_init_and_metadata(temp_db):
    set_metadata("test_key", "test_val")
    assert get_metadata("test_key") == "test_val"
    assert get_metadata("non_existent", "default_val") == "default_val"

def test_token_sources(temp_db):
    # Override token passed directly
    assert get_effective_github_token(override_token="ghp_direct") == "ghp_direct"

    # No token set
    with patch.dict(os.environ, {}, clear=True):
        set_metadata("github_token", "")
        assert get_effective_github_token() is None
        assert get_token_source() == "None"

        # Env token
        with patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_envtoken123"}):
            assert get_effective_github_token() == "ghp_envtoken123"
            assert get_token_source() == "Environment Variable"

        # DB token overrides env
        set_metadata("github_token", "ghp_dbtoken456")
        assert get_effective_github_token() == "ghp_dbtoken456"
        assert get_token_source() == "Database"

@pytest.mark.asyncio
async def test_execute_tool_search_code():
    mock_hit = MagicMock()
    mock_hit.score = 0.05
    mock_hit.payload = {
        "repo": "test-repo",
        "rel_path": "server.py",
        "start_line": 1,
        "end_line": 20,
        "symbol": "run_server",
        "github_url": "https://github.com/test/blob/main/server.py",
        "language": "python",
        "content": "def run_server(): pass"
    }

    with patch("app.mcp.tools.execute_hybrid_search", return_value=[mock_hit]):
        res = await execute_tool("search_code", {"query": "run server", "repo": "test-repo", "language": "python"})
        assert len(res) == 1
        assert "server.py" in res[0].text
        assert "run_server" in res[0].text

    # No results
    with patch("app.mcp.tools.execute_hybrid_search", return_value=[]):
        res = await execute_tool("search_code", {"query": "nonexistent"})
        assert "No matching code snippets found" in res[0].text

    # Empty query
    res_empty = await handle_search_code(query="")
    assert "Error: search query cannot be empty" in res_empty

    # Error during search
    with patch("app.mcp.tools.execute_hybrid_search", side_effect=Exception("Hybrid search crash")):
        res_err = await handle_search_code(query="crash test")
        assert "Error executing code search" in res_err

@pytest.mark.asyncio
async def test_execute_tool_search_docs():
    mock_hit = MagicMock()
    mock_hit.score = 0.04
    mock_hit.payload = {
        "repo": "docs",
        "rel_path": "arch.md",
        "heading": "Overview",
        "tags": ["design"],
        "github_url": "https://github.com/docs/arch.md",
        "content": "# Overview of architecture"
    }

    with patch("app.mcp.tools.execute_hybrid_search", return_value=[mock_hit]):
        res = await execute_tool("search_docs", {"query": "architecture", "category": "arch", "tag": "design"})
        assert len(res) == 1
        assert "arch.md" in res[0].text
        assert "Overview of architecture" in res[0].text
        assert "GitHub Link" in res[0].text

    # Empty query
    res_empty = await handle_search_docs(query="")
    assert "Error: search query cannot be empty" in res_empty

    # No hits
    with patch("app.mcp.tools.execute_hybrid_search", return_value=[]):
        res_nohit = await handle_search_docs(query="not_found")
        assert "No matching documentation found" in res_nohit

    # Search error
    with patch("app.mcp.tools.execute_hybrid_search", side_effect=Exception("Doc search crash")):
        res_err = await handle_search_docs(query="crash")
        assert "Error executing doc search" in res_err

@pytest.mark.asyncio
async def test_execute_tool_find_symbol(temp_db):
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("my-repo", "src/auth.py", "authenticate", "AuthService.authenticate", "method", 10, 25, "def authenticate(user, pwd)", "python")
        )
        conn.commit()

    # Exact match
    res = await execute_tool("find_symbol", {"name": "authenticate", "exact": True, "repo": "my-repo"})
    assert len(res) == 1
    assert "AuthService.authenticate" in res[0].text or "authenticate" in res[0].text
    assert "src/auth.py" in res[0].text

    # Fuzzy match
    res_fuzzy = await handle_find_symbol(name="auth", exact=False, repo="my-repo")
    assert "Found 1 matching symbols" in res_fuzzy

    # Empty name
    res_empty = await handle_find_symbol(name="")
    assert "Error: symbol name cannot be empty" in res_empty

    # Not found
    res_nf = await execute_tool("find_symbol", {"name": "not_found", "exact": True})
    assert "No symbols found matching" in res_nf[0].text

    # DB exception
    with patch("app.mcp.tools.get_db_connection", side_effect=Exception("AST DB error")):
        res_err = await handle_find_symbol(name="anything")
        assert "Error finding symbol" in res_err

@pytest.mark.asyncio
async def test_execute_tool_get_file_outline(temp_db):
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("my-repo", "src/auth.py", "authenticate", "AuthService.authenticate", "method", 10, 25, "def authenticate(user, pwd)", "python")
        )
        conn.commit()

    res = await execute_tool("get_file_outline", {"filepath": "src/auth.py", "repo": "my-repo"})
    assert len(res) == 1
    assert "File Outline: src/auth.py" in res[0].text
    assert "authenticate" in res[0].text

    res_empty = await execute_tool("get_file_outline", {"filepath": "nonexistent.py"})
    assert "No outline available" in res_empty[0].text

    with patch("app.mcp.tools.get_db_connection", side_effect=Exception("Outline query error")):
        res_err = await handle_get_file_outline(filepath="src/auth.py")
        assert "Failed to get outline" in res_err

@pytest.mark.asyncio
async def test_execute_tool_list_repositories(temp_db):
    with get_db_connection() as conn:
        conn.execute("INSERT INTO git_repositories (name, url, branch, commit_sha, status, last_synced) VALUES ('repo-a', 'http://url', 'main', 'abcdef1234', 'synced', '2026-08-17')")
        conn.execute("INSERT INTO indexed_paths (path, repo, category, enabled) VALUES ('/local/path', 'local-repo', 'notes', 1)")
        conn.execute("INSERT INTO indexed_files (filepath, repo, doc_type, language) VALUES ('/local/path/f.md', 'local-repo', 'doc', 'markdown')")
        conn.commit()

    res = await execute_tool("list_repositories", {})
    assert len(res) == 1
    assert "repo-a" in res[0].text
    assert "local-repo" in res[0].text

    with patch("app.mcp.tools.get_db_connection", side_effect=Exception("Repo list error")):
        res_err = await handle_list_repositories()
        assert "Error listing repositories" in res_err

@pytest.mark.asyncio
async def test_execute_tool_sync_repository(temp_db):
    with patch("app.services.indexer.run_full_indexing"), \
         patch("app.services.indexer.sync_single_git_repo"):
        # Sync all
        res_all = await execute_tool("sync_repository", {})
        assert "Triggered full background re-indexing" in res_all[0].text

        # Sync specific repo
        with get_db_connection() as conn:
            conn.execute("INSERT INTO git_repositories (name, url, branch, status) VALUES ('repo-b', 'http://url', 'main', 'synced')")
            conn.commit()

        res_repo = await execute_tool("sync_repository", {"repo": "repo-b"})
        assert "Triggered background sync for repo: 'repo-b'" in res_repo[0].text

    with patch("app.mcp.tools.get_db_connection", side_effect=Exception("Sync crash")):
        res_err = await handle_sync_repository(repo="repo-b")
        assert "Failed to trigger sync" in res_err

@pytest.mark.asyncio
async def test_execute_tool_index_status(temp_db):
    mock_vs_cfg = {
        "provider": "qdrant",
        "mode": "embedded",
        "storage_path": "/path/to/storage",
        "collection": "knowledge_rag_v1",
        "stats": {"points_count": 500},
        "healthy": True,
    }
    with patch("app.mcp.tools.get_vector_store_config", return_value=mock_vs_cfg), \
         patch("app.services.git_manager.check_github_rate_limit", return_value={"remaining": 5000, "limit": 5000}):
        res = await execute_tool("index_status", {})
        assert len(res) == 1
        assert "Total Hybrid Vectors: 500" in res[0].text
        assert "Vector Store Provider: QDRANT" in res[0].text
        assert "5000 / 5000" in res[0].text


    with patch("app.mcp.tools.get_db_connection", side_effect=Exception("Status DB fail")):
        res_err = await handle_index_status()
        assert "Failed to get status" in res_err

@pytest.mark.asyncio
async def test_catalog_summary(temp_db):
    with get_db_connection() as conn:
        conn.execute("INSERT INTO git_repositories (name, url, branch, commit_sha, status, last_synced) VALUES ('repo-c', 'http://url', 'main', '12345678', 'synced', '2026-08-17')")
        conn.commit()

    res = await handle_catalog_summary()
    assert "repo-c" in res
    assert "Registered Git Repositories" in res

    with patch("app.mcp.tools.get_db_connection", side_effect=Exception("Catalog DB fail")):
        res_err = await handle_catalog_summary()
        assert "Error generating catalog resource" in res_err

def test_custom_prompt_handlers():
    res1 = handle_search_infrastructure_docs(topic="docker swarm")
    assert "docker swarm" in res1

    res2 = handle_find_implementation_symbol(symbol="execute_tool", repo="mcp-server")
    assert "execute_tool" in res2
    assert "mcp-server" in res2

def test_register_mcp_tools():
    # Register with mock server
    mock_server = MagicMock()
    mock_tool_manager = MagicMock()
    mock_tool_manager.list_tools.return_value = []
    mock_server._tool_manager = mock_tool_manager

    register_mcp_tools_and_resources(server=mock_server)
    assert mock_server.tool.call_count >= 2

    # Register with default server=None
    with patch("app.mcp.mcp_server.mcp_server", mock_server):
        register_mcp_tools_and_resources(server=None)

@pytest.mark.asyncio
async def test_execute_tool_unknown():
    with pytest.raises(ValueError, match="Unknown tool: invalid_tool_name"):
        await execute_tool("invalid_tool_name", {})

@pytest.mark.asyncio
async def test_read_resource_and_prompt(temp_db):
    # Valid Resource
    res_text = await read_resource("notes://catalog/summary")
    assert "Repository & Documentation Catalog" in res_text

    # Invalid Resource
    with pytest.raises(ValueError, match="Unknown resource URI"):
        await read_resource("invalid://uri")

    # Prompt
    prompt_messages = await get_prompt("search_infrastructure_docs", {"topic": "docker"})
    assert len(prompt_messages) == 1
    assert "docker" in prompt_messages[0].content.text

    # Prompt failure
    with patch("app.mcp.tools.get_db_connection", side_effect=Exception("Prompt DB error")):
        with pytest.raises(ValueError, match="Failed to get prompt"):
            await get_prompt("search_infrastructure_docs")
