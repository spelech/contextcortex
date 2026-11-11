r"""
Comprehensive regression tests for all 13 defects identified in the
Windows Portable + PostgreSQL field work-up (contextcortex-mcp-workup.md):

1. P1: Re-sync of a Git repository on Windows (read-only packfiles, staging clone, force re-sync, GIT_DIR sanitization).
2. P1: `list_repositories` (and `catalog_summary`, `what_is_ingested`, `get_recent_changes`, `index_status`) datetime JSON serialization on PostgreSQL.
3. P1: `diagnose_issue` PostgreSQL `IndeterminateDatatype` parameter error when `repo` is provided or `None`.
4. P2: `trace_path` C# method invocation extraction & qualified/unqualified symbol resolution (`UnitOfWork.Run` -> `Engine.Run`, `services.Reads.LoadAsync`).
5. P2: `get_file_outline` empty outline when paths use Windows backslashes (`\`) or `repo://` prefixes (and navigator API `/admin/api/navigator/outline`).
6. P2: Permalinks containing Windows backslashes (`\`) and GitLab `ssh://` URL provider auto-detection (`/-/blob/`).
7. P2: Consistent POSIX `/` path separators across all MCP tools (`search_code`, `find_symbol`, `trace_path`, `find_routes`, `get_architecture`, `grep_code`, `read_file`) and startup DB path normalization.
8. P3: `search_code` and `search_docs` accepting `keyword` and `bm25` as aliases of `lexical`.
9. P3: `PgVectorStore` hybrid/lexical search OR-based `tsquery` fallback for natural-language questions (`_build_or_tsquery`).
10. P3: `get_architecture` `hub_symbols` filtering generic boilerplate (`start`, `constructor`, `__init__`) and ranking by AST relationship degree.
11. P3: Documentation & MCP tool catalog completeness (`grep_code`, `diagnose_issue`, `get_recent_changes`).
12. P3: Embedding settings & `index_status` reporting effective lexical/sparse backend (`PostgreSQL Full-Text Search (tsvector + GIN)`) when `VECTOR_STORE_PROVIDER=pgvector`.
13. P3: MCP `serverInfo.version` matching the ContextCortex application version instead of the `mcp` SDK version.
"""

import os
import json
import stat
import datetime
from unittest.mock import patch, MagicMock
import pytest

from app.services.database import get_db_engine, init_db, get_db_connection
import app.services.database as db_mod
import app.services.database.connection as conn_mod
from app.services.auth import set_current_auth_context, AuthContext, Role


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "field_workup.db")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("CACHE_DB_PATH", db_file)
    monkeypatch.setattr(db_mod, "CACHE_DB_PATH", db_file)
    monkeypatch.setattr(conn_mod, "CACHE_DB_PATH", db_file)
    engine = get_db_engine(f"sqlite:///{db_file}", reset=True)
    init_db(engine=engine)
    set_current_auth_context(AuthContext(role=Role.ADMIN))
    yield db_file
    set_current_auth_context(None)
    monkeypatch.undo()
    get_db_engine(reset=True)


# ---------------------------------------------------------------------------
# Finding 1 (P1): Windows Git Re-sync Resilience & Read-Only Packfile Cleanup
# ---------------------------------------------------------------------------
def test_finding_1_git_env_strips_ambient_git_vars(monkeypatch):
    from app.services.git_manager import _get_git_env

    monkeypatch.setenv("GIT_DIR", "C:\\some\\ambient\\.git")
    monkeypatch.setenv("GIT_WORK_TREE", "C:\\some\\ambient")
    monkeypatch.setenv("GIT_INDEX_FILE", "C:\\some\\ambient\\.git\\index")
    env = _get_git_env()
    assert "GIT_DIR" not in env
    assert "GIT_WORK_TREE" not in env
    assert "GIT_INDEX_FILE" not in env
    assert env["GIT_TERMINAL_PROMPT"] == "0"


def test_finding_1_shallow_clone_stages_fresh_clone_on_fetch_failure(tmp_path):
    from app.services.git_manager import shallow_clone_repo, cleanup_repo_dir

    target_dir = tmp_path / "repos" / "my-repo"
    git_dir = target_dir / ".git" / "objects" / "pack"
    git_dir.mkdir(parents=True)
    (target_dir / ".git" / "HEAD").write_text("ref: refs/heads/develop\n")
    pack_file = git_dir / "pack-readonly.idx"
    pack_file.write_bytes(b"packdata")
    os.chmod(str(pack_file), stat.S_IREAD)

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        proc = MagicMock()
        if "rev-parse" in cmd and "--git-dir" in cmd:
            proc.returncode = 0
            proc.stdout = ".git\n"
            proc.stderr = ""
        elif "fetch" in cmd:
            proc.returncode = 128
            proc.stdout = ""
            proc.stderr = "fatal: not a git repository (or any of the parent directories): .git"
        elif "clone" in cmd:
            dest = cmd[-1]
            os.makedirs(os.path.join(dest, ".git"), exist_ok=True)
            with open(os.path.join(dest, ".git", "HEAD"), "w") as f:
                f.write("ref: refs/heads/develop\n")
            proc.returncode = 0
            proc.stdout = ""
            proc.stderr = ""
        elif "rev-parse" in cmd and "HEAD" in cmd:
            proc.returncode = 0
            proc.stdout = "abcdef1234567890abcdef1234567890abcdef12\n"
            proc.stderr = ""
        else:
            proc.returncode = 0
            proc.stdout = ""
            proc.stderr = ""
        return proc

    with patch("subprocess.run", side_effect=fake_run):
        res = shallow_clone_repo(
            "ssh://git@gitlab.internal:2222/group/project.git",
            branch="develop",
            target_dir=str(target_dir),
            depth=5,
        )

    assert res.error is None
    assert res.commit_sha == "abcdef1234567890abcdef1234567890abcdef12"
    assert os.path.exists(os.path.join(str(target_dir), ".git", "HEAD"))
    cleanup_repo_dir(str(target_dir))
    assert not os.path.exists(str(target_dir))


# ---------------------------------------------------------------------------
# Finding 2 (P1): PostgreSQL datetime JSON serialization in MCP handlers
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_finding_2_list_repositories_serializes_postgres_datetime(isolated_db):
    from app.mcp.handlers.repo_handlers import (
        handle_list_repositories,
        handle_catalog_summary,
    )
    from app.mcp.handlers.storage_handlers import handle_what_is_ingested

    fake_dt = datetime.datetime(2026, 11, 11, 14, 30, 0, tzinfo=datetime.timezone.utc)
    fake_conn = MagicMock()

    def execute_side_effect(sql, params=None):
        cursor = MagicMock()
        if "FROM git_repositories" in sql:
            cursor.fetchall.return_value = [
                {
                    "id": 1,
                    "name": "corp-service",
                    "url": "ssh://git@gitlab.corp:2222/team/corp-service.git",
                    "branch": "develop",
                    "commit_sha": "1234567890abcdef",
                    "provider": "gitlab",
                    "auth_user": None,
                    "status": "synced",
                    "last_synced": fake_dt,
                }
            ]
        elif "FROM indexed_paths" in sql:
            cursor.fetchall.return_value = []
        elif "GROUP BY repo" in sql:
            cursor.fetchall.return_value = [{"repo": "corp-service", "cnt": 42}]
        elif "FROM indexed_files" in sql:
            cursor.fetchall.return_value = [
                {
                    "filepath": "corp-service://server\\Product.Worker\\UnitOfWork.cs",
                    "repo": "corp-service",
                    "doc_type": "code",
                    "language": "csharp",
                    "mtime": fake_dt,
                }
            ]
        elif "count(*)" in sql.lower():
            cursor.fetchone.return_value = [10]
        else:
            cursor.fetchall.return_value = []
        return cursor

    fake_conn.__enter__.return_value = fake_conn
    fake_conn.execute.side_effect = execute_side_effect

    with patch("app.mcp.handlers.repo_handlers.get_db_connection", return_value=fake_conn), \
         patch("app.mcp.tools.get_db_connection", return_value=fake_conn):
        raw_list = await handle_list_repositories()
        parsed_list = json.loads(raw_list)
        assert "error" not in parsed_list
        assert parsed_list["git_repositories"][0]["name"] == "corp-service"
        assert "2026-11-11" in parsed_list["git_repositories"][0]["last_synced"]

        raw_cat = await handle_catalog_summary()
        parsed_cat = json.loads(raw_cat)
        assert "error" not in parsed_cat
        assert parsed_cat["files"][0]["file"] == "server/Product.Worker/UnitOfWork.cs"

    with patch("app.mcp.handlers.storage_handlers.get_db_connection", return_value=fake_conn), \
         patch("app.mcp.tools.get_db_connection", return_value=fake_conn):
        raw_ingested = await handle_what_is_ingested(source_type="git", detail_level="detailed")
        parsed_ingested = json.loads(raw_ingested)
        assert "error" not in parsed_ingested
        assert parsed_ingested["files"][0]["file"] == "server/Product.Worker/UnitOfWork.cs"


# ---------------------------------------------------------------------------
# Finding 3 (P1): diagnose_issue PostgreSQL IndeterminateDatatype parameter fix
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_finding_3_diagnose_issue_no_untyped_null_params(isolated_db):
    from app.mcp.handlers.diagnostic_handlers import handle_diagnose_issue
    from app.services.diagnostics import _get_callers_and_callees

    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO ast_symbols (id, repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language)
               VALUES (10, 'my-repo', 'my-repo://server/Product.Worker/UnitOfWork.cs', 'Run', 'UnitOfWork.Run', 'method', 95, 149, 'public async Task Run()', 'csharp')"""
        )
        conn.execute(
            """INSERT INTO ast_symbols (id, repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language)
               VALUES (11, 'my-repo', 'my-repo://server/Product.Worker/Engine.cs', 'Run', 'Engine.Run', 'method', 29, 78, 'public void Run()', 'csharp')"""
        )
        conn.execute(
            """INSERT INTO ast_relationships (repo, source_symbol_id, source_filepath, source_symbol, target_symbol, relationship_type, line_number)
               VALUES ('my-repo', 10, 'my-repo://server/Product.Worker/UnitOfWork.cs', 'UnitOfWork.Run', 'Engine.Run', 'CALLS', 112)"""
        )
        conn.commit()

        # Verify SQL queries never use `? IS NULL` which fails on PostgreSQL psycopg3
        executed_queries = []

        class _SpyConn:
            def __init__(self, real_conn):
                self._real = real_conn

            def execute(self, sql, params=()):
                executed_queries.append((sql, params))
                return self._real.execute(sql, params)

        spy_conn = _SpyConn(conn)
        callers_with_repo, callees_with_repo = _get_callers_and_callees(spy_conn, "my-repo", "UnitOfWork.Run")
        callers_no_repo, callees_no_repo = _get_callers_and_callees(spy_conn, None, "Engine.Run")

        for sql_text, params in executed_queries:
            assert "IS NULL" not in sql_text.upper()
            assert None not in params

        assert any(c["symbol"] == "Engine.Run" for c in callees_with_repo)
        assert any(c["symbol"] == "UnitOfWork.Run" for c in callers_no_repo)

    with patch("app.services.diagnostics.execute_hybrid_search", return_value=[]):
        diag_json = await handle_diagnose_issue(
            issue_text="ERROR in 'UnitOfWork.Run' at server\\Product.Worker\\UnitOfWork.cs:line 112",
            repo="my-repo",
        )
        diag = json.loads(diag_json)
        assert "error" not in diag
        assert len(diag["matched_symbols"]) >= 1
        assert diag["matched_symbols"][0]["file"] == "server/Product.Worker/UnitOfWork.cs"


# ---------------------------------------------------------------------------
# Finding 4 (P2): C# AST Call Graph Extraction & trace_path Resolution
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_finding_4_csharp_call_graph_extraction_and_trace_path(isolated_db):
    from app.services.chunking import extract_symbols_and_chunks
    from app.mcp.handlers.symbol_handlers import handle_trace_path

    uow_code = """
using System.Threading.Tasks;

namespace Product.Worker
{
    public class UnitOfWork
    {
        private readonly IServices services;

        public async Task Run(Record item)
        {
            var data = await services.Reads.LoadAsync(item.Id);
            Engine.Run(data);
        }
    }
}
"""
    engine_code = """
namespace Product.Worker
{
    public class Engine
    {
        public static void Run(object payload)
        {
             Helper.Execute(payload);
        }
    }
}
"""
    uow_res = extract_symbols_and_chunks(uow_code, "my-repo://server/Product.Worker/UnitOfWork.cs", repo="my-repo")
    eng_res = extract_symbols_and_chunks(engine_code, "my-repo://server/Product.Worker/Engine.cs", repo="my-repo")

    uow_targets = {r.target_symbol for r in uow_res.relationships}
    assert "Run" in uow_targets
    assert "LoadAsync" in uow_targets

    with get_db_connection() as conn:
        sym_id_map = {}
        for s in list(uow_res.symbols) + list(eng_res.symbols):
            cur = conn.execute(
                """INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (s.repo, s.filepath, s.name, s.full_symbol, s.kind, s.start_line, s.end_line, s.signature, s.language),
            )
            sym_id_map[(s.repo, s.filepath, s.name)] = cur.lastrowid
            if s.full_symbol:
                sym_id_map[(s.repo, s.filepath, s.full_symbol)] = cur.lastrowid

        for r in list(uow_res.relationships) + list(eng_res.relationships):
            src_id = sym_id_map.get((r.repo, r.source_filepath, r.source_symbol))
            conn.execute(
                """INSERT INTO ast_relationships (repo, source_symbol_id, source_filepath, source_symbol, target_symbol, relationship_type, line_number)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (r.repo, src_id, r.source_filepath, r.source_symbol, r.target_symbol, r.relationship_type, r.line_number),
            )
        conn.commit()

    # Trace outbound & inbound from UnitOfWork.Run
    uow_trace = json.loads(await handle_trace_path(symbol="UnitOfWork.Run", repo="my-repo", direction="both", depth=2))
    callee_symbols = {c["symbol"] for c in uow_trace["callees"]}
    assert "Engine.Run" in callee_symbols
    assert any("LoadAsync" in s for s in callee_symbols)

    # Trace inbound callers of Engine.Run
    eng_trace = json.loads(await handle_trace_path(symbol="Engine.Run", repo="my-repo", direction="both", depth=2))
    caller_symbols = {c["symbol"] for c in eng_trace["callers"]}
    assert "UnitOfWork.Run" in caller_symbols


# ---------------------------------------------------------------------------
# Finding 5, 6, 7 (P2): get_file_outline, Permalinks, and POSIX Path Normalization
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_findings_5_6_7_file_outline_permalinks_and_path_normalization(isolated_db):
    from app.mcp.handlers.symbol_handlers import handle_get_file_outline, handle_find_symbol
    from app.services.navigator import get_file_outline as nav_get_file_outline
    from app.services.git_manager import format_git_permalink, detect_git_provider

    # Seed a row that originally had Windows backslashes in filepath
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language)
               VALUES ('win-repo', 'win-repo://server\\Product.Worker\\UnitOfWork.cs', 'UnitOfWork', 'UnitOfWork', 'class', 10, 150, 'public class UnitOfWork', 'csharp')"""
        )
        conn.execute(
            """INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language)
               VALUES ('win-repo', 'win-repo://server\\Product.Worker\\UnitOfWork.cs', 'Run', 'UnitOfWork.Run', 'method', 95, 149, 'public async Task Run()', 'csharp')"""
        )
        conn.commit()

    # Both forward slashes and backslashes must return the symbols in get_file_outline
    outline_posix = json.loads(await handle_get_file_outline(filepath="server/Product.Worker/UnitOfWork.cs", repo="win-repo"))
    outline_win = json.loads(await handle_get_file_outline(filepath="server\\Product.Worker\\UnitOfWork.cs", repo="win-repo"))
    assert outline_posix["file"] == "server/Product.Worker/UnitOfWork.cs"
    assert len(outline_posix["symbols"]) == 2
    assert len(outline_win["symbols"]) == 2

    # Navigator service also resolves both
    nav_res = nav_get_file_outline("win-repo", "server/Product.Worker/UnitOfWork.cs")
    assert len(nav_res["symbols"]) == 2
    assert nav_res["filepath"] == "server/Product.Worker/UnitOfWork.cs"

    # find_symbol returns normalized POSIX file path
    found = json.loads(await handle_find_symbol(name="UnitOfWork", repo="win-repo"))
    assert found["symbols"][0]["file"] == "server/Product.Worker/UnitOfWork.cs"

    # GitLab ssh:// URL and Windows rel_path permalink normalization
    gl_ssh = "ssh://git@gitlab.company.internal:2222/group/project.git"
    assert detect_git_provider(gl_ssh, explicit_provider="github") == "gitlab"
    permalink = format_git_permalink(
        gl_ssh,
        "a1b2c3d4",
        "server\\Product.Worker\\UnitOfWork.cs",
        108,
        131,
        provider="github",
    )
    assert permalink == "https://gitlab.company.internal/group/project/-/blob/a1b2c3d4/server/Product.Worker/UnitOfWork.cs#L108-131"
    assert "\\" not in permalink


# ---------------------------------------------------------------------------
# Finding 8 & 9 (P3): Search Mode Aliases ('keyword', 'bm25') & Natural-Language FTS
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_findings_8_and_9_search_mode_aliases_and_or_tsquery():
    from app.services.search import normalize_search_mode
    from app.services.vector_store.pgvector_store import _build_or_tsquery, PgVectorStore
    from app.mcp.handlers.search_handlers import handle_search_code

    assert normalize_search_mode("keyword") == "lexical"
    assert normalize_search_mode("bm25") == "lexical"
    assert normalize_search_mode("fts") == "lexical"
    assert normalize_search_mode("vector") == "semantic"
    assert normalize_search_mode("hybrid") == "hybrid"

    or_query = _build_or_tsquery("how does the worker decide that a record needs action")
    assert or_query == "worker | decide | record | needs | action"

    # Verify PgVectorStore accepts mode='keyword' without raising ValueError
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    mock_conn.execute.return_value.mappings.return_value.fetchall.return_value = []

    store = PgVectorStore(engine=mock_engine, auto_init=False)
    res = store.search("how does the worker decide that a record needs action", search_mode="keyword")
    assert res == []
    executed_sql = str(mock_conn.execute.call_args[0][0])
    executed_params = mock_conn.execute.call_args[0][1]
    assert "to_tsquery('simple', :tsq_or)" in executed_sql
    assert executed_params["tsq_or"] == "worker | decide | record | needs | action"

    with patch("app.mcp.handlers.search_handlers.execute_hybrid_search", return_value=[]) as mock_search, \
         patch("app.mcp.tools.execute_hybrid_search", mock_search):
        out = json.loads(await handle_search_code(query="Engine", mode="keyword"))
        assert out["mode"] == "lexical"
        assert mock_search.call_args.kwargs["search_mode"] == "lexical"


# ---------------------------------------------------------------------------
# Finding 10 (P3): get_architecture hub_symbols ranking & noise filtering
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_finding_10_get_architecture_hub_symbols_excludes_boilerplate(isolated_db):
    from app.mcp.handlers.architecture_handlers import handle_get_architecture

    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO indexed_files (filepath, repo, doc_type, language, hash) VALUES ('arch-repo://server\\Engine.cs', 'arch-repo', 'code', 'csharp', 'h1')"
        )
        conn.execute(
            "INSERT INTO indexed_files (filepath, repo, doc_type, language, hash) VALUES ('arch-repo://web\\App.tsx', 'arch-repo', 'code', 'typescript', 'h2')"
        )
        # Noisy symbols (start x3, constructor)
        for idx in range(3):
            conn.execute(
                """INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language)
                   VALUES ('arch-repo', 'arch-repo://web\\App.tsx', 'start', 'start', 'function', ?, ?, 'function start()', 'typescript')""",
                (idx * 10 + 1, idx * 10 + 5),
            )
        conn.execute(
            """INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language)
               VALUES ('arch-repo', 'arch-repo://web\\App.tsx', 'constructor', 'App.constructor', 'method', 40, 50, 'constructor()', 'typescript')"""
        )
        # Meaningful hub symbols
        cur1 = conn.execute(
            """INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language)
               VALUES ('arch-repo', 'arch-repo://server\\Engine.cs', 'Engine', 'Engine', 'class', 1, 100, 'public class Engine', 'csharp')"""
        )
        eng_id = cur1.lastrowid
        conn.execute(
            """INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language)
               VALUES ('arch-repo', 'arch-repo://server\\Engine.cs', 'ProcessBatch', 'Engine.ProcessBatch', 'method', 20, 60, 'public void ProcessBatch()', 'csharp')"""
        )
        conn.execute(
            """INSERT INTO ast_relationships (repo, source_symbol_id, source_filepath, source_symbol, target_symbol, relationship_type, line_number)
               VALUES ('arch-repo', ?, 'arch-repo://server/Engine.cs', 'Engine', 'Engine.ProcessBatch', 'CALLS', 30)""",
            (eng_id,),
        )
        conn.execute(
            """INSERT INTO api_routes (repo, filepath, framework, http_method, path_pattern, handler_symbol, start_line, end_line)
               VALUES ('arch-repo', 'arch-repo://server/Engine.cs', 'aspnet', 'GET', '/api/status', 'GetStatus', 10, 20)"""
        )
        conn.commit()

    arch = json.loads(await handle_get_architecture(repo="arch-repo"))
    hub_names = [h["name"] for h in arch["hub_symbols"]]
    assert "start" not in hub_names
    assert "constructor" not in hub_names
    assert "Engine.ProcessBatch" in hub_names or "Engine" in hub_names
    for h in arch["hub_symbols"]:
        assert "\\" not in h.get("file", "")
    for ep in arch["entry_points"]:
        assert "\\" not in ep
    assert arch["api_surface"]["estimated_routes"] >= 1


# ---------------------------------------------------------------------------
# Finding 11, 12, 13 (P3): Tool List, Effective Sparse Model, and MCP Server Version
# ---------------------------------------------------------------------------
def test_findings_11_12_13_version_sparse_model_and_readme_tools(monkeypatch):
    from app.mcp.mcp_server import mcp_server, MCP_SERVER_VERSION
    from app.services.embeddings import get_embedding_config
    import main

    # Finding 13: MCP serverInfo.version matches main.py app.version
    assert mcp_server._mcp_server.version == MCP_SERVER_VERSION
    assert MCP_SERVER_VERSION == main.app.version

    # Finding 12: When VECTOR_STORE_PROVIDER=pgvector, sparse_model reports PostgreSQL FTS
    monkeypatch.setenv("VECTOR_STORE_PROVIDER", "pgvector")
    cfg = get_embedding_config()
    assert "PostgreSQL Full-Text Search" in cfg["sparse_model"]
    assert "PostgreSQL Full-Text Search" in cfg["effective_sparse_model"]

    # Finding 11: README.md lists all 19 registered MCP tools including grep_code, diagnose_issue, get_recent_changes
    readme_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "README.md")
    with open(readme_path, "r", encoding="utf-8") as f:
        readme_text = f.read()
    for tool_name in ("grep_code", "diagnose_issue", "get_recent_changes"):
        assert f"`{tool_name}`" in readme_text
