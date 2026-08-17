import os
import sqlite3
import pytest
from unittest.mock import patch, MagicMock
from app.services.db import (
    init_db, get_db_connection, set_metadata, get_metadata,
    get_effective_github_token, get_token_source
)
from app.mcp.tools import execute_tool, read_resource, get_prompt
from mcp.types import TextContent

@pytest.fixture
def temp_db(tmp_path):
    db_file = str(tmp_path / "test_rag.db")
    with patch("app.services.db.CACHE_DB_PATH", db_file):
        init_db()
        yield db_file

def test_db_init_and_metadata(temp_db):
    set_metadata("test_key", "test_val")
    assert get_metadata("test_key") == "test_val"
    assert get_metadata("non_existent", "default_val") == "default_val"

def test_token_sources(temp_db):
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
        res = await execute_tool("search_code", {"query": "run server", "repo": "test-repo"})
        assert len(res) == 1
        assert "server.py" in res[0].text
        assert "run_server" in res[0].text

    # No results
    with patch("app.mcp.tools.execute_hybrid_search", return_value=[]):
        res = await execute_tool("search_code", {"query": "nonexistent"})
        assert "No matching code snippets found" in res[0].text

@pytest.mark.asyncio
async def test_execute_tool_search_docs():
    mock_hit = MagicMock()
    mock_hit.score = 0.04
    mock_hit.payload = {
        "repo": "docs",
        "rel_path": "arch.md",
        "heading": "Overview",
        "tags": ["design"],
        "github_url": "",
        "content": "# Overview of architecture"
    }

    with patch("app.mcp.tools.execute_hybrid_search", return_value=[mock_hit]):
        res = await execute_tool("search_docs", {"query": "architecture"})
        assert len(res) == 1
        assert "arch.md" in res[0].text
        assert "Overview of architecture" in res[0].text

@pytest.mark.asyncio
async def test_execute_tool_find_symbol(temp_db):
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("my-repo", "src/auth.py", "authenticate", "AuthService.authenticate", "method", 10, 25, "def authenticate(user, pwd)", "python")
        )
        conn.commit()

    res = await execute_tool("find_symbol", {"name": "authenticate", "exact": True})
    assert len(res) == 1
    assert "AuthService.authenticate" in res[0].text or "authenticate" in res[0].text
    assert "src/auth.py" in res[0].text

    # Not found
    res_nf = await execute_tool("find_symbol", {"name": "not_found", "exact": True})
    assert "No symbols found matching" in res_nf[0].text

@pytest.mark.asyncio
async def test_execute_tool_get_file_outline(temp_db):
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("my-repo", "src/auth.py", "authenticate", "AuthService.authenticate", "method", 10, 25, "def authenticate(user, pwd)", "python")
        )
        conn.commit()

    res = await execute_tool("get_file_outline", {"filepath": "src/auth.py"})
    assert len(res) == 1
    assert "File Outline: src/auth.py" in res[0].text
    assert "authenticate" in res[0].text

    res_empty = await execute_tool("get_file_outline", {"filepath": "nonexistent.py"})
    assert "No outline available" in res_empty[0].text

@pytest.mark.asyncio
async def test_execute_tool_list_repositories(temp_db):
    with get_db_connection() as conn:
        conn.execute("INSERT INTO git_repositories (name, url, branch, status) VALUES ('repo-a', 'http://url', 'main', 'synced')")
        conn.commit()

    res = await execute_tool("list_repositories", {})
    assert len(res) == 1
    assert "repo-a" in res[0].text

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

@pytest.mark.asyncio
async def test_execute_tool_index_status(temp_db):
    with patch("app.services.indexer.qdrant") as mock_qdrant, \
         patch("app.services.git_manager.check_github_rate_limit", return_value={"remaining": 5000, "limit": 5000}):
        mock_qdrant.collection_exists.return_value = True
        mock_info = MagicMock()
        mock_info.points_count = 500
        mock_qdrant.get_collection.return_value = mock_info

        res = await execute_tool("index_status", {})
        assert len(res) == 1
        assert "Total Hybrid Vectors: 500" in res[0].text
        assert "5000 / 5000" in res[0].text

@pytest.mark.asyncio
async def test_read_resource_and_prompt(temp_db):
    # Resource
    res_text = await read_resource("notes://catalog/summary")
    assert "Repository & Documentation Catalog" in res_text

    # Prompt
    prompt_messages = await get_prompt("search_infrastructure_docs", {"topic": "docker"})
    assert len(prompt_messages) == 1
    assert "docker" in prompt_messages[0].content.text
