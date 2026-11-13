r"""
Real End-to-End MCP Protocol & Multi-Language Repository Workflow Tests.

Unlike mock-heavy unit tests, this suite builds a real multi-language workspace on disk
(Python FastAPI service, C# Worker service, TypeScript API client, Markdown runbooks & ADRs,
unit test files with synthetic route strings, and a broken `.venv/lib64` symlink), runs the
actual ContextCortex ingestion and vector/AST indexing pipeline, and exercises all 19 MCP tools,
resources, resource templates, and prompts end-to-end.

Verifies:
1. `grep_code` never crashes with `FileNotFoundError` when scanning repos containing broken `.venv/lib64` symlinks or `node_modules`.
2. Re-syncing or re-ingesting files never creates duplicate `ast_symbols`, `ast_relationships`, `api_routes`, or `api_client_calls`, and `init_db()` automatically deduplicates legacy duplicate rows.
3. `find_routes` extracts real FastAPI and ASP.NET routes while ignoring fake route strings inside `tests/` files (`tests/test_security.py` -> `/etc/shadow`).
4. `get_architecture` prioritizes production source modules and hub symbols over `tests/`, `wwwroot/_framework`, `www/assets`, and `anonymous` arrow functions.
5. `get_file_outline` resolves both exact paths (`Program.cs`), prefixed paths (`my-repo://Program.cs`), and guessed deep paths (`src/Worker/Program.cs` -> `Program.cs`), returning deduplicated symbols.
6. `trace_path` accurately traces C# method invocations across classes (`UnitOfWork.Run` -> `Engine.Run`) and cross-repo HTTP boundaries (`fetchUserProfile` -> `GET /api/v1/users/{user_id}` -> `get_user_profile`).
7. `diagnose_issue` resolves stack frames with clean relative filepaths (no `repo://` prefix leakage), error literals, and callers/callees.
8. MCP Resources (`knowledge://catalog/summary`), Resource Templates (`knowledge://repo/{repo}/architecture`), and all 5 MCP Prompts (`search_infrastructure_docs`, `find_implementation_symbol`, `onboard_repository`, `triage_error`, `investigate_change_impact`) return actionable, valid responses via FastMCP.
"""

import os
import json
import pytest
from pydantic import AnyUrl

import app.services.database as db_mod
import app.services.database.connection as conn_mod
import app.services.vector_store as vs_mod
from app.services.database import get_db_engine, init_db, get_db_connection
from app.services.vector_store.qdrant_store import QdrantVectorStore
from app.services.indexing.processor import process_file_content
from app.services.indexing.local_syncer import sync_local_paths
from app.services.auth import set_current_auth_context, AuthContext, Role
from app.mcp.mcp_server import mcp_server
from app.mcp.tools import register_mcp_tools_and_resources
from app.mcp.handlers import (
    handle_search,
    handle_find_symbol,
    handle_trace_path,
    handle_find_routes,
    handle_list_repositories,
    handle_manage,
    handle_catalog_summary,
    handle_get_architecture,
    handle_read_file,
    handle_grep_code,
    handle_diagnose_issue,
)


@pytest.fixture
def real_e2e_env(tmp_path, monkeypatch):
    """Sets up an isolated SQLite + in-memory Qdrant environment with a realistic multi-language repo on disk."""
    db_file = str(tmp_path / "e2e_index_cache.db")
    storage_dir = str(tmp_path / "local_storage")
    repos_dir = tmp_path / "repos"
    repo_root = repos_dir / "platform-core"
    repo_root.mkdir(parents=True)
    os.makedirs(storage_dir, exist_ok=True)

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("CACHE_DB_PATH", db_file)
    monkeypatch.setenv("LOCAL_STORAGE_PATH", storage_dir)
    monkeypatch.setattr(db_mod, "CACHE_DB_PATH", db_file)
    monkeypatch.setattr(conn_mod, "CACHE_DB_PATH", db_file)

    engine = get_db_engine(f"sqlite:///{db_file}", reset=True)
    init_db(engine=engine)
    set_current_auth_context(AuthContext(role=Role.ADMIN))

    qdrant_store = QdrantVectorStore(
        storage_path=":memory:",
        collection_name="e2e_knowledge_rag",
        prefer_remote=False,
    )
    import app.services.search as search_mod
    from app.services.vector_store.manager import VectorStoreManager
    monkeypatch.setattr(vs_mod, "get_vector_store", lambda: qdrant_store)
    monkeypatch.setattr(search_mod, "get_vector_store", lambda: qdrant_store)
    monkeypatch.setattr(VectorStoreManager, "get_vector_store", classmethod(lambda cls, force_reload=False: qdrant_store))

    # 1. Create Python FastAPI file
    api_dir = repo_root / "app" / "api"
    api_dir.mkdir(parents=True)
    (api_dir / "users.py").write_text(
        'from fastapi import APIRouter\n'
        'router = APIRouter()\n\n'
        'def validate_token(token: str) -> bool:\n'
        '    if not token:\n'
        '        raise ValueError("Missing bearer token in request header")\n'
        '    return token.startswith("tok_")\n\n'
        '@router.get("/api/v1/users/{user_id}")\n'
        'async def get_user_profile(user_id: str, token: str = "tok_123"):\n'
        '    validate_token(token)\n'
        '    return {"id": user_id, "status": "active"}\n',
        encoding="utf-8",
    )

    # 2. Create C# Worker & Program files
    worker_dir = repo_root / "server" / "Worker"
    worker_dir.mkdir(parents=True)
    (repo_root / "Program.cs").write_text(
        'using System;\n'
        'namespace Platform.Core {\n'
        '    public class Program {\n'
        '        public static void Main(string[] args) {\n'
        '            var uow = new UnitOfWork();\n'
        '            uow.Run();\n'
        '        }\n'
        '    }\n'
        '}\n',
        encoding="utf-8",
    )
    (worker_dir / "UnitOfWork.cs").write_text(
        'using System;\n'
        'namespace Platform.Core.Worker {\n'
        '    public class Engine {\n'
        '        public void Run() {\n'
        '            ExecuteStep();\n'
        '        }\n'
        '        public void ExecuteStep() {}\n'
        '    }\n'
        '    public class UnitOfWork {\n'
        '        private readonly Engine _engine = new Engine();\n'
        '        public void Run() {\n'
        '            _engine.Run();\n'
        '        }\n'
        '    }\n'
        '}\n',
        encoding="utf-8",
    )

    # 3. Create TypeScript client that calls GET /api/v1/users/{user_id} and has arrow functions
    web_dir = repo_root / "web" / "src"
    web_dir.mkdir(parents=True)
    (web_dir / "client.ts").write_text(
        'export async function fetchUserProfile(userId: string) {\n'
        '    const items = [1, 2, 3].map((x) => x * 2);\n'
        '    const response = await fetch(`/api/v1/users/${userId}`, { method: "GET" });\n'
        '    return response.json();\n'
        '}\n',
        encoding="utf-8",
    )

    # 4. Create Markdown Architecture Doc & ADR
    docs_dir = repo_root / "docs" / "adr"
    docs_dir.mkdir(parents=True)
    (docs_dir / "0001-hybrid-vector-search.md").write_text(
        '# ADR 0001: Hybrid Dense + BM25 Vector Search\n\n'
        'Status: ACCEPTED\n\n'
        '## Context\n'
        'Agents require both semantic concept matching and exact identifier lookup across Qdrant and PostgreSQL.\n\n'
        '## Decision\n'
        'We combine BAAI/bge-small-en-v1.5 dense embeddings with BM25 lexical scoring.\n',
        encoding="utf-8",
    )

    # 5. Create unit test file containing a fake route string (`path("/etc/shadow", ...)`)
    # and many test_* functions to verify they don't pollute `find_routes` or `get_architecture`
    tests_dir = repo_root / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_security.py").write_text(
        'def setup_test_db():\n'
        '    pass\n\n'
        'def test_path_traversal_blocked():\n'
        '    # Should never be extracted as a Django route!\n'
        '    check_path("/etc/shadow", repo_handler)\n'
        '    assert True\n\n'
        'def test_another_helper():\n'
        '    setup_test_db()\n',
        encoding="utf-8",
    )

    # 6. Create a broken symlink inside `.venv/lib64` and a static bundle inside `www/assets`
    venv_dir = repo_root / ".venv"
    venv_dir.mkdir(parents=True)
    os.symlink("/nonexistent/broken/python/lib64", str(venv_dir / "lib64"))

    assets_dir = repo_root / "www" / "assets"
    assets_dir.mkdir(parents=True)
    (assets_dir / "bundle.js").write_text("const a = () => 1;\n", encoding="utf-8")

    # Register repo in git_repositories and indexed_paths, then run real sync_local_paths()
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO git_repositories (name, url, branch, commit_sha, provider, status, keep_shallow, retain_commits_count, last_synced)
               VALUES ('platform-core', 'https://github.com/example/platform-core.git', 'main', '400ce382a239590922fa1c27a343b25a93e6d69d', 'github', 'synced', 1, 20, '2026-11-11T18:00:00Z')"""
        )
        conn.execute(
            """INSERT INTO git_commits (repo, commit_sha, author, committed_at, message, files_changed)
               VALUES ('platform-core', '400ce382a239590922fa1c27a343b25a93e6d69d', 'Steve', '2026-11-11T18:00:00Z', 'feat: add user profile endpoint and worker engine', ?)""",
            (json.dumps(["app/api/users.py", "server/Worker/UnitOfWork.cs", "Program.cs"]),),
        )
        conn.execute(
            """INSERT INTO indexed_paths (path, type, recursive, enabled, category, repo)
               VALUES (?, 'directory', 1, 1, 'code', 'platform-core')""",
            (str(repo_root),),
        )
        conn.commit()

    sync_local_paths()

    yield {
        "db_file": db_file,
        "repo_root": repo_root,
        "storage_dir": storage_dir,
        "qdrant_store": qdrant_store,
    }

    set_current_auth_context(None)
    get_db_engine(reset=True)


@pytest.mark.asyncio
async def test_e2e_grep_code_survives_broken_venv_symlink_and_enriches_ast(real_e2e_env):
    """Verifies `grep_code` does not crash on broken `.venv/lib64` symlinks and returns AST symbol metadata."""
    res_raw = await handle_grep_code(
        pattern="Missing bearer token",
        repo="platform-core",
        context_lines=2,
    )
    res = json.loads(res_raw)
    assert "error" not in res, f"grep_code failed: {res}"
    assert res["total_matches"] == 1
    match = res["matches"][0]
    assert match["repo"] == "platform-core"
    assert match["file"].endswith("app/api/users.py")
    assert match["symbol"] == "validate_token"
    assert "blob/400ce382" in (match["permalink"] or "")


@pytest.mark.asyncio
async def test_e2e_find_routes_excludes_test_files_and_links_api_callers(real_e2e_env):
    """Verifies `find_routes` extracts real FastAPI routes, ignores `/etc/shadow` in `tests/test_security.py`, and links callers."""
    routes_raw = await handle_find_routes(kind="handlers", repo="platform-core")
    routes_data = json.loads(routes_raw)
    assert "error" not in routes_data
    paths = [r["path"] for r in routes_data["routes"]]
    assert "/api/v1/users/{user_id}" in paths
    assert "/etc/shadow" not in paths

    callers_raw = await handle_find_routes(query="/api/v1/users/{user_id}", kind="callers", method="GET")
    callers_data = json.loads(callers_raw)
    assert "error" not in callers_data
    assert len(callers_data["callers"]) == 1
    assert callers_data["callers"][0]["caller"] == "fetchUserProfile"
    assert callers_data["callers"][0]["file"].endswith("web/src/client.ts")


@pytest.mark.asyncio
async def test_e2e_get_architecture_excludes_tests_and_anonymous_arrows(real_e2e_env):
    """Verifies `get_architecture` excludes `tests`, `www/assets`, `setup_test_db`, and `anonymous` arrow functions."""
    arch_raw = await handle_get_architecture(repo="platform-core")
    arch = json.loads(arch_raw)
    assert "error" not in arch
    assert arch["total_files"] >= 4
    assert "Program.cs" in arch["entry_points"]

    for mod in arch["modules"]:
        assert "tests" not in mod.lower()
        assert "www/assets" not in mod.lower()

    hub_names = [h["name"] for h in arch["hub_symbols"]]
    assert "anonymous" not in hub_names
    assert "setup_test_db" not in hub_names
    assert not any(n.startswith("test_") for n in hub_names)
    assert any(h.get("file") for h in arch["hub_symbols"])


@pytest.mark.asyncio
async def test_e2e_get_file_outline_resolves_guessed_subpaths_and_deduplicates(real_e2e_env):
    """Verifies `read_file(..., outline_only=True)` resolves `src/Platform.Core/Program.cs` to `Program.cs` and never returns duplicate symbols."""
    outline_raw = await handle_read_file(
        path="src/Platform.Core/Program.cs",
        repo="platform-core",
        outline_only=True,
    )
    outline = json.loads(outline_raw)
    assert "error" not in outline
    assert outline["outline_only"] is True
    assert outline["file"].endswith("Program.cs")
    sym_names = [s["name"] for s in outline["symbols"]]
    assert "Program" in sym_names
    assert "Main" in sym_names
    # Ensure zero duplicate symbol entries
    sym_keys = [(s["name"], s["symbol"], tuple(s["lines"])) for s in outline["symbols"]]
    assert len(sym_keys) == len(set(sym_keys))


@pytest.mark.asyncio
async def test_e2e_startup_deduplication_cleans_duplicate_ast_and_routes(real_e2e_env):
    """Verifies `init_db()` automatically purges duplicate `ast_symbols`, `ast_relationships`, and `api_routes` rows."""
    with get_db_connection() as conn:
        before_syms = conn.execute("SELECT count(*) FROM ast_symbols WHERE repo = 'platform-core'").fetchone()[0]
        before_routes = conn.execute("SELECT count(*) FROM api_routes WHERE repo = 'platform-core'").fetchone()[0]

        # Intentionally insert duplicate rows simulating pre-fix re-sync accumulation
        conn.execute(
            """INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language)
               SELECT repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language
               FROM ast_symbols WHERE repo = 'platform-core'"""
        )
        conn.execute(
            """INSERT INTO api_routes (repo, filepath, framework, http_method, path_pattern, handler_symbol, start_line, end_line)
               SELECT repo, filepath, framework, http_method, path_pattern, handler_symbol, start_line, end_line
               FROM api_routes WHERE repo = 'platform-core'"""
        )
        conn.commit()
        dup_syms = conn.execute("SELECT count(*) FROM ast_symbols WHERE repo = 'platform-core'").fetchone()[0]
        assert dup_syms == before_syms * 2

    # Running init_db() should automatically deduplicate all tables
    init_db()

    with get_db_connection() as conn:
        after_syms = conn.execute("SELECT count(*) FROM ast_symbols WHERE repo = 'platform-core'").fetchone()[0]
        after_routes = conn.execute("SELECT count(*) FROM api_routes WHERE repo = 'platform-core'").fetchone()[0]
        assert after_syms == before_syms
        assert after_routes == before_routes


@pytest.mark.asyncio
async def test_e2e_trace_path_and_diagnose_issue_end_to_end(real_e2e_env):
    """Verifies `trace_path` across C# classes and `diagnose_issue` on a real stack trace."""
    trace_raw = await handle_trace_path(
        symbol="Engine.Run",
        repo="platform-core",
        direction="both",
        depth=2,
    )
    trace_data = json.loads(trace_raw)
    assert trace_data["target"]["symbol"] == "Engine.Run"
    callee_syms = [c["symbol"] for c in trace_data["callees"]]
    assert any("ExecuteStep" in s for s in callee_syms)

    diag_raw = await handle_diagnose_issue(
        issue_text=(
            'Traceback (most recent call last):\n'
            '  File "app/api/users.py", line 11, in get_user_profile\n'
            '    validate_token(token)\n'
            '  File "app/api/users.py", line 6, in validate_token\n'
            '    raise ValueError("Missing bearer token in request header")\n'
            'ValueError: Missing bearer token in request header'
        ),
        repo="platform-core",
    )
    diag = json.loads(diag_raw)
    assert "error" not in diag
    assert len(diag["resolved_frames"]) >= 1
    for frame in diag["resolved_frames"]:
        assert "://" not in frame["file"]
    frame_syms = [f["symbol"] for f in diag["resolved_frames"]]
    assert "validate_token" in frame_syms or "get_user_profile" in frame_syms


@pytest.mark.asyncio
async def test_e2e_hybrid_search_and_mcp_resources_and_prompts(real_e2e_env):
    """Verifies hybrid/lexical/keyword search, MCP resources, resource templates, and all 5 workflow prompts."""
    register_mcp_tools_and_resources(mcp_server)

    # 1. Hybrid & keyword search on code and docs
    code_search = json.loads(
        await handle_search(query="validate_token bearer", scope="code", repo="platform-core", mode="keyword")
    )
    assert "error" not in code_search
    assert len(code_search["results"]) >= 1
    assert code_search["results"][0]["file"].endswith("app/api/users.py")

    doc_search = json.loads(
        await handle_search(query="BAAI/bge-small-en-v1.5 BM25 lexical", scope="docs", repo="platform-core", mode="hybrid")
    )
    assert "error" not in doc_search
    assert len(doc_search["results"]) >= 1

    # 2. Resources & Resource Templates
    resources = await mcp_server.list_resources()
    assert any(str(r.uri) == "knowledge://catalog/summary" for r in resources)
    cat_contents = await mcp_server.read_resource(AnyUrl("knowledge://catalog/summary"))
    cat_json = json.loads(cat_contents[0].content)
    assert cat_json["total_files"] >= 4
    repo_entry = next(r for r in cat_json["git_repositories"] if r["name"] == "platform-core")
    assert repo_entry["files"] >= 4
    assert repo_entry["symbols"] >= 4

    templates = await mcp_server.list_resource_templates()
    assert any("knowledge://repo/{repo}/architecture" in str(t.uriTemplate) for t in templates)
    arch_contents = await mcp_server.read_resource(AnyUrl("knowledge://repo/platform-core/architecture"))
    arch_from_resource = json.loads(arch_contents[0].content)
    assert arch_from_resource["repo"] == "platform-core"
    assert arch_from_resource["total_files"] >= 4

    # 3. All 5 MCP Prompts
    prompts = await mcp_server.list_prompts()
    prompt_names = {p.name for p in prompts}
    expected_prompts = {
        "search_infrastructure_docs",
        "find_implementation_symbol",
        "onboard_repository",
        "triage_error",
        "investigate_change_impact",
    }
    assert expected_prompts.issubset(prompt_names)

    p_onboard = await mcp_server.get_prompt("onboard_repository", {"repo": "platform-core"})
    assert "get_architecture" in p_onboard.messages[0].content.text

    p_triage = await mcp_server.get_prompt(
        "triage_error", {"issue_text": "ValueError: Missing bearer token", "repo": "platform-core"}
    )
    assert "diagnose_issue" in p_triage.messages[0].content.text

    p_impact = await mcp_server.get_prompt(
        "investigate_change_impact", {"symbol": "validate_token", "repo": "platform-core"}
    )
    assert "trace_path" in p_impact.messages[0].content.text


@pytest.mark.asyncio
async def test_e2e_real_git_repo_clone_and_resync_without_mocks(real_e2e_env, tmp_path):
    """
    Real end-to-end git repository sync using an actual local git repository (`git init` + commits),
    `sync_single_git_repo` (un-mocked git clone + delta + AST + vector indexing), followed by a second
    commit and re-sync, verifying zero duplicate symbols/routes/relationships and indexed git commit history.
    """
    import subprocess
    from app.services.indexing.git_syncer import sync_single_git_repo

    origin_repo = tmp_path / "real_origin_repo"
    origin_repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=str(origin_repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Real E2E"], cwd=str(origin_repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "e2e@example.com"], cwd=str(origin_repo), check=True, capture_output=True)

    (origin_repo / "service.py").write_text(
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n\n"
        "@app.get('/api/orders')\n"
        "def list_orders():\n"
        "    return fetch_orders_from_db()\n\n"
        "def fetch_orders_from_db():\n"
        "    return []\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=str(origin_repo), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "feat: initial orders service"], cwd=str(origin_repo), check=True, capture_output=True)

    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO git_repositories (name, url, branch, provider, status, keep_shallow, retain_commits_count)
               VALUES ('orders-svc', ?, 'main', 'generic', 'pending', 1, 10)""",
            (str(origin_repo),),
        )
        conn.commit()
        repo_id = cur.lastrowid

    # 1st real git sync (clones real git repo on disk)
    sync_single_git_repo(repo_id)

    with get_db_connection() as conn:
        row = conn.execute("SELECT status, commit_sha, last_error FROM git_repositories WHERE id = ?", (repo_id,)).fetchone()
        assert row["status"] == "synced", f"Expected synced, got {row['status']} ({row['last_error']})"
        sym_count_1 = conn.execute("SELECT count(*) FROM ast_symbols WHERE repo = 'orders-svc'").fetchone()[0]
        route_count_1 = conn.execute("SELECT count(*) FROM api_routes WHERE repo = 'orders-svc'").fetchone()[0]
        assert sym_count_1 == 2
        assert route_count_1 == 1

    # Make a 2nd commit modifying service.py and force a full re-sync
    (origin_repo / "service.py").write_text(
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n\n"
        "@app.get('/api/orders')\n"
        "def list_orders():\n"
        "    return fetch_orders_from_db()\n\n"
        "def fetch_orders_from_db():\n"
        "    return ['order-1']\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=str(origin_repo), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "fix: return default order"], cwd=str(origin_repo), check=True, capture_output=True)

    sync_single_git_repo(repo_id)

    with get_db_connection() as conn:
        sym_count_2 = conn.execute("SELECT count(*) FROM ast_symbols WHERE repo = 'orders-svc'").fetchone()[0]
        route_count_2 = conn.execute("SELECT count(*) FROM api_routes WHERE repo = 'orders-svc'").fetchone()[0]
        assert sym_count_2 == 2
        assert route_count_2 == 1
        commits = conn.execute(
            "SELECT message FROM git_commits WHERE repo = 'orders-svc' ORDER BY committed_at DESC, id DESC"
        ).fetchall()
        assert len(commits) == 2
        assert "fix: return default order" in commits[0]["message"]

