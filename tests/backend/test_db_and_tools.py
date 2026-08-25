import os
import sqlite3
import pytest
from unittest.mock import patch, MagicMock
from app.services.database import (
    init_db, get_db_connection, set_metadata, get_metadata,
    get_effective_git_token, get_default_db_path
)
import app.mcp.tools as tools_module
from app.mcp.tools import (
    handle_search_code, handle_search_docs, handle_find_symbol,
    handle_get_file_outline, handle_list_repositories, handle_sync_repository,
    handle_index_status, handle_catalog_summary, handle_search_infrastructure_docs,
    handle_find_implementation_symbol, register_mcp_tools_and_resources
)

@pytest.fixture
def temp_db(tmp_path):
    db_file = str(tmp_path / "test_rag.db")
    with patch("app.services.database.CACHE_DB_PATH", db_file):
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
    with patch("app.services.database.CACHE_DB_PATH", db_file):
        init_db(vault_path=str(vault_dir))
        with sqlite3.connect(db_file) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT path, repo FROM indexed_paths").fetchall()
            assert len(rows) == 1
            assert rows[0]["repo"] == "vault"

def test_db_init_seeding_errors(tmp_path):
    db_file = str(tmp_path / "test_err_seed.db")
    with patch("app.services.database.CACHE_DB_PATH", db_file):
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

        with patch("app.services.database.get_db_connection", return_value=mock_conn):
            init_db(vault_path=str(tmp_path))

def test_db_metadata_errors(temp_db):
    with patch("app.services.database.get_db_connection", side_effect=Exception("DB down")):
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
    tok, _, src = get_effective_git_token("https://github.com", override_token="ghp_direct", provider="github")
    assert tok == "ghp_direct"
    assert src == "Repository Override"


    # No token set
    with patch.dict(os.environ, {}, clear=True):
        set_metadata("github_token", "")
        tok, _, src = get_effective_git_token("https://github.com", provider="github")
        assert tok is None
        assert src == "None"

        # Env token
        with patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_envtoken123"}):
            tok, _, src = get_effective_git_token("https://github.com", provider="github")
            assert tok == "ghp_envtoken123"
            assert src == "Environment Variable (GITHUB_TOKEN)"


        # DB token overrides env
        set_metadata("github_token", "ghp_dbtoken456")
        tok, _, src = get_effective_git_token("https://github.com", provider="github")
        assert tok == "ghp_dbtoken456"
        assert src == "Database (Github)"

@pytest.mark.asyncio
async def test_handle_search_code():
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
        res = await handle_search_code(query="run server", repo="test-repo", language="python")
        assert "server.py" in res
        assert "run_server" in res

    # No results
    with patch("app.mcp.tools.execute_hybrid_search", return_value=[]):
        res = await handle_search_code(query="nonexistent")
        assert "No matching code snippets found" in res

    # Empty query
    res_empty = await handle_search_code(query="")
    assert "Error: search query cannot be empty" in res_empty

    # Error during search
    with patch("app.mcp.tools.execute_hybrid_search", side_effect=Exception("Hybrid search crash")):
        res_err = await handle_search_code(query="crash test")
        assert "Error executing code search" in res_err

@pytest.mark.asyncio
async def test_handle_search_docs():
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
        res = await handle_search_docs(query="architecture", category="arch", tag="design")
        assert "arch.md" in res
        assert "Overview of architecture" in res
        assert "Source Link" in res

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
async def test_handle_find_symbol(temp_db):
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("my-repo", "src/auth.py", "authenticate", "AuthService.authenticate", "method", 10, 25, "def authenticate(user, pwd)", "python")
        )
        conn.commit()

    # Exact match
    res = await handle_find_symbol(name="authenticate", exact=True, repo="my-repo")
    assert "AuthService.authenticate" in res or "authenticate" in res
    assert "src/auth.py" in res

    # Fuzzy match
    res_fuzzy = await handle_find_symbol(name="auth", exact=False, repo="my-repo")
    assert "Found 1 matching symbols" in res_fuzzy

    # Empty name
    res_empty = await handle_find_symbol(name="")
    assert "Error: symbol name cannot be empty" in res_empty

    # Not found
    res_nf = await handle_find_symbol(name="not_found", exact=True)
    assert "No symbols found matching" in res_nf

    # DB exception
    with patch("app.mcp.tools.get_db_connection", side_effect=Exception("AST DB error")):
        res_err = await handle_find_symbol(name="anything")
        assert "Error finding symbol" in res_err

@pytest.mark.asyncio
async def test_handle_get_file_outline(temp_db):
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("my-repo", "src/auth.py", "authenticate", "AuthService.authenticate", "method", 10, 25, "def authenticate(user, pwd)", "python")
        )
        conn.commit()

    res = await handle_get_file_outline(filepath="src/auth.py", repo="my-repo")
    assert "File Outline: src/auth.py" in res
    assert "authenticate" in res

    res_empty = await handle_get_file_outline(filepath="nonexistent.py")
    assert "No outline available" in res_empty

    with patch("app.mcp.tools.get_db_connection", side_effect=Exception("Outline query error")):
        res_err = await handle_get_file_outline(filepath="src/auth.py")
        assert "Failed to get outline" in res_err

@pytest.mark.asyncio
async def test_handle_list_repositories(temp_db):
    with get_db_connection() as conn:
        conn.execute("INSERT INTO git_repositories (name, url, branch, commit_sha, status, last_synced) VALUES ('repo-a', 'http://url', 'main', 'abcdef1234', 'synced', '2026-08-17')")
        conn.execute("INSERT INTO indexed_paths (path, repo, category, enabled) VALUES ('/local/path', 'local-repo', 'notes', 1)")
        conn.execute("INSERT INTO indexed_files (filepath, repo, doc_type, language) VALUES ('/local/path/f.md', 'local-repo', 'doc', 'markdown')")
        conn.commit()

    res = await handle_list_repositories()
    assert "repo-a" in res
    assert "local-repo" in res

    with patch("app.mcp.tools.get_db_connection", side_effect=Exception("Repo list error")):
        res_err = await handle_list_repositories()
        assert "Error listing repositories" in res_err

@pytest.mark.asyncio
async def test_handle_sync_repository(temp_db):
    with patch("app.services.indexing.run_full_indexing"), \
         patch("app.services.indexing.sync_single_git_repo"):
        # Sync all
        res_all = await handle_sync_repository()
        assert "Triggered full background re-indexing" in res_all

        # Sync specific repo
        with get_db_connection() as conn:
            conn.execute("INSERT INTO git_repositories (name, url, branch, status) VALUES ('repo-b', 'http://url', 'main', 'synced')")
            conn.commit()

        res_repo = await handle_sync_repository(repo="repo-b")
        assert "Triggered background sync for repo: 'repo-b'" in res_repo

    with patch("app.mcp.tools.get_db_connection", side_effect=Exception("Sync crash")):
        res_err = await handle_sync_repository(repo="repo-b")
        assert "Failed to trigger sync" in res_err

@pytest.mark.asyncio
async def test_handle_index_status(temp_db):
    mock_vs_cfg = {
        "provider": "qdrant",
        "mode": "embedded",
        "storage_path": "/path/to/storage",
        "collection": "knowledge_rag_v1",
        "stats": {"points_count": 500},
        "healthy": True,
    }
    with patch("app.mcp.tools.get_vector_store_config", return_value=mock_vs_cfg), \
         patch("app.services.database.get_effective_git_token", return_value=("ghp_token123", None, "Database (Github)")), \
         patch("app.services.git_manager.check_github_rate_limit", return_value={"remaining": 5000, "limit": 5000}):
        res = await handle_index_status()
        assert "Total Vectors: 500" in res
        assert "Vector Store Provider: QDRANT" in res
        assert "5000 / 5000" in res

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

    res2 = handle_find_implementation_symbol(symbol="handle_search_code", repo="mcp-server")
    assert "handle_search_code" in res2
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
