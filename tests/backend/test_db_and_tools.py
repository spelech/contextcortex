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

    # Empty query and no-match checks on real store
    res_empty_code = json.loads(await handle_search_code(query=""))
    assert "search query cannot be empty" in res_empty_code["error"]
    res_empty_doc = json.loads(await handle_search_docs(query=""))
    assert "search query cannot be empty" in res_empty_doc["error"]
    res_nomatch = json.loads(await handle_search_code(query="anything", repo="nonexistent-repo-xyz"))
    assert res_nomatch["results"] == []

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

@pytest.mark.asyncio
async def test_catalog_summary(temp_db):
    import json
    with get_db_connection() as conn:
        conn.execute("INSERT INTO git_repositories (name, url, branch, commit_sha, status, last_synced) VALUES ('repo-c', 'http://url', 'main', '12345678', 'synced', '2026-08-17')")
        conn.commit()

    res = json.loads(await handle_catalog_summary())
    assert any(r["name"] == "repo-c" for r in res["git_repositories"])

def test_custom_prompt_handlers():
    import json
    res1 = json.loads(handle_search_infrastructure_docs(topic="docker swarm"))
    assert res1["topic"] == "docker swarm"

    res2 = json.loads(handle_find_implementation_symbol(symbol="handle_search_code", repo="mcp-server"))
    assert res2["symbol"] == "handle_search_code"
    assert res2["repo"] == "mcp-server"

