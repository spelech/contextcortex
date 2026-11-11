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
from app.services.vector_store import VectorDocument, VectorStoreManager

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
    import json
    mock_hit = MagicMock()
    mock_hit.score = 0.05
    mock_hit.dense_score = None
    mock_hit.sparse_score = None
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
        res = json.loads(await handle_search_code(query="run server", repo="test-repo", language="python"))
        assert res["results"][0]["file"] == "server.py"
        assert res["results"][0]["symbol"] == "run_server"
        assert res["results"][0]["score"] == 0.05

    # No results
    with patch("app.mcp.tools.execute_hybrid_search", return_value=[]):
        res = json.loads(await handle_search_code(query="nonexistent"))
        assert res["results"] == []

    # Empty query
    res_empty = json.loads(await handle_search_code(query=""))
    assert "search query cannot be empty" in res_empty["error"]

    # Error during search
    with patch("app.mcp.tools.execute_hybrid_search", side_effect=Exception("Hybrid search crash")):
        res_err = json.loads(await handle_search_code(query="crash test"))
        assert "Error executing code search" in res_err["error"]

@pytest.mark.asyncio
async def test_handle_search_docs():
    import json
    mock_hit = MagicMock()
    mock_hit.score = 0.04
    mock_hit.dense_score = None
    mock_hit.sparse_score = None
    mock_hit.payload = {
        "repo": "docs",
        "rel_path": "arch.md",
        "heading": "Overview",
        "tags": ["design"],
        "github_url": "https://github.com/docs/arch.md",
        "content": "# Overview of architecture"
    }

    with patch("app.mcp.tools.execute_hybrid_search", return_value=[mock_hit]):
        res = json.loads(await handle_search_docs(query="architecture", category="arch", tag="design"))
        assert res["results"][0]["file"] == "arch.md"
        assert "Overview of architecture" in res["results"][0]["content"]
        assert res["results"][0]["permalink"] == "https://github.com/docs/arch.md"
        assert res["results"][0]["score"] == 0.04

    # Empty query
    res_empty = json.loads(await handle_search_docs(query=""))
    assert "search query cannot be empty" in res_empty["error"]

    # No hits
    with patch("app.mcp.tools.execute_hybrid_search", return_value=[]):
        res_nohit = json.loads(await handle_search_docs(query="not_found"))
        assert res_nohit["results"] == []

    # Search error
    with patch("app.mcp.tools.execute_hybrid_search", side_effect=Exception("Doc search crash")):
        res_err = json.loads(await handle_search_docs(query="crash"))
        assert "Error executing doc search" in res_err["error"]

@pytest.mark.asyncio
async def test_handle_search_code_and_docs_real_integration(tmp_path):
    """Real un-mocked verification of handle_search_code and handle_search_docs MCP tools."""
    import json
    storage_path = str(tmp_path / "qdrant_tools_test")
    collection_name = "test_tools_rag"

    from app.services.database import set_vector_store_db_config
    from app.services.vector_store import get_vector_store

    set_vector_store_db_config(
        provider="qdrant",
        mode="embedded",
        storage_path=storage_path,
        url="",
        collection=collection_name,
    )
    VectorStoreManager.reset_instance()
    store = get_vector_store(force_reload=True)

    doc1 = VectorDocument(
        id="code-auth-1",
        text="def authenticate_jwt_user(token: str) -> bool:\n    '''Validates bearer JWT token claims and scopes.'''\n    return True",
        repo="gateway-core",
        doc_type="code",
        language="python",
        path="app/auth.py",
        rel_path="app/auth.py",
        title="auth.py",
        symbol="authenticate_jwt_user",
        start_line=1,
        end_line=3,
    )
    doc2 = VectorDocument(
        id="doc-arch-1",
        text="# System Architecture\nContextCortex uses hybrid vector and BM25 lexical retrieval.",
        repo="docs-vault",
        doc_type="doc",
        path="docs/architecture.md",
        rel_path="docs/architecture.md",
        title="architecture.md",
        heading="System Architecture",
        start_line=1,
        end_line=2,
    )
    assert store.upsert_documents([doc1, doc2]) is True

    # Real un-mocked code search via MCP tool
    res_code = json.loads(await handle_search_code(query="authenticate JWT user", repo="gateway-core"))
    assert res_code["results"][0]["file"] == "app/auth.py"
    assert res_code["results"][0]["symbol"] == "authenticate_jwt_user"
    assert "Validates bearer JWT token" in res_code["results"][0]["content"]
    assert "score" in res_code["results"][0]

    # Real un-mocked doc search via MCP tool
    res_doc = json.loads(await handle_search_docs(query="hybrid BM25 retrieval", repo="docs-vault"))
    assert res_doc["results"][0]["file"] == "docs/architecture.md"
    assert res_doc["results"][0]["heading"] == "System Architecture"
    assert "score" in res_doc["results"][0]

@pytest.mark.asyncio
async def test_handle_find_symbol(temp_db):
    import json
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("my-repo", "src/auth.py", "authenticate", "AuthService.authenticate", "method", 10, 25, "def authenticate(user, pwd)", "python")
        )
        conn.commit()

    # Exact match
    res = json.loads(await handle_find_symbol(name="authenticate", exact=True, repo="my-repo"))
    assert res["symbols"][0]["symbol"] == "AuthService.authenticate"
    assert res["symbols"][0]["file"] == "src/auth.py"

    # Fuzzy match
    res_fuzzy = json.loads(await handle_find_symbol(name="auth", exact=False, repo="my-repo"))
    assert len(res_fuzzy["symbols"]) == 1

    # Empty name
    res_empty = json.loads(await handle_find_symbol(name=""))
    assert "symbol name cannot be empty" in res_empty["error"]

    # Not found
    res_nf = json.loads(await handle_find_symbol(name="not_found", exact=True))
    assert res_nf["symbols"] == []

    # DB exception
    with patch("app.mcp.tools.get_db_connection", side_effect=Exception("AST DB error")):
        res_err = json.loads(await handle_find_symbol(name="anything"))
        assert "Error finding symbol" in res_err["error"]

@pytest.mark.asyncio
async def test_handle_get_file_outline(temp_db):
    import json
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("my-repo", "src/auth.py", "authenticate", "AuthService.authenticate", "method", 10, 25, "def authenticate(user, pwd)", "python")
        )
        conn.commit()

    res = json.loads(await handle_get_file_outline(filepath="src/auth.py", repo="my-repo"))
    assert res["file"] == "src/auth.py"
    assert res["symbols"][0]["name"] == "authenticate"

    res_empty = json.loads(await handle_get_file_outline(filepath="nonexistent.py"))
    assert res_empty["symbols"] == []

    with patch("app.mcp.tools.get_db_connection", side_effect=Exception("Outline query error")):
        res_err = json.loads(await handle_get_file_outline(filepath="src/auth.py"))
        assert "Failed to get outline" in res_err["error"]

@pytest.mark.asyncio
async def test_handle_list_repositories(temp_db):
    import json
    with get_db_connection() as conn:
        conn.execute("INSERT INTO git_repositories (name, url, branch, commit_sha, status, last_synced) VALUES ('repo-a', 'http://url', 'main', 'abcdef1234', 'synced', '2026-08-17')")
        conn.execute("INSERT INTO indexed_paths (path, repo, category, enabled) VALUES ('/local/path', 'local-repo', 'notes', 1)")
        conn.execute("INSERT INTO indexed_files (filepath, repo, doc_type, language) VALUES ('/local/path/f.md', 'local-repo', 'doc', 'markdown')")
        conn.commit()

    res = json.loads(await handle_list_repositories())
    assert any(r["name"] == "repo-a" for r in res["git_repositories"])
    assert any(lp["repo"] == "local-repo" for lp in res["local_paths"])

    with patch("app.mcp.tools.get_db_connection", side_effect=Exception("Repo list error")):
        res_err = json.loads(await handle_list_repositories())
        assert "Error listing repositories" in res_err["error"]

@pytest.mark.asyncio
async def test_handle_sync_repository(temp_db):
    import json
    with patch("app.services.indexing.run_full_indexing"), \
         patch("app.services.indexing.sync_single_git_repo"):
        # Sync all
        res_all = json.loads(await handle_sync_repository())
        assert res_all["status"] == "triggered"
        assert res_all["scope"] == "full"

        # Sync specific repo
        with get_db_connection() as conn:
            conn.execute("INSERT INTO git_repositories (name, url, branch, status) VALUES ('repo-b', 'http://url', 'main', 'synced')")
            conn.commit()

        res_repo = json.loads(await handle_sync_repository(repo="repo-b"))
        assert res_repo["status"] == "triggered"
        assert res_repo["repo"] == "repo-b"

    with patch("app.mcp.tools.get_db_connection", side_effect=Exception("Sync crash")):
        res_err = json.loads(await handle_sync_repository(repo="repo-b"))
        assert "Failed to trigger sync" in res_err["error"]

@pytest.mark.asyncio
async def test_handle_index_status(temp_db):
    import json
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
        res = json.loads(await handle_index_status())
        assert res["vector_store"]["total_vectors"] == 500
        assert res["vector_store"]["provider"] == "QDRANT"
        assert res["github_rate_limit"]["remaining"] == 5000

    with patch("app.mcp.tools.get_db_connection", side_effect=Exception("Status DB fail")):
        res_err = json.loads(await handle_index_status())
        assert "Failed to get status" in res_err["error"]

@pytest.mark.asyncio
async def test_catalog_summary(temp_db):
    import json
    with get_db_connection() as conn:
        conn.execute("INSERT INTO git_repositories (name, url, branch, commit_sha, status, last_synced) VALUES ('repo-c', 'http://url', 'main', '12345678', 'synced', '2026-08-17')")
        conn.commit()

    res = json.loads(await handle_catalog_summary())
    assert any(r["name"] == "repo-c" for r in res["git_repositories"])

    with patch("app.mcp.tools.get_db_connection", side_effect=Exception("Catalog DB fail")):
        res_err = json.loads(await handle_catalog_summary())
        assert "Error generating catalog resource" in res_err["error"]

def test_custom_prompt_handlers():
    import json
    res1 = json.loads(handle_search_infrastructure_docs(topic="docker swarm"))
    assert res1["topic"] == "docker swarm"

    res2 = json.loads(handle_find_implementation_symbol(symbol="handle_search_code", repo="mcp-server"))
    assert res2["symbol"] == "handle_search_code"
    assert res2["repo"] == "mcp-server"

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
