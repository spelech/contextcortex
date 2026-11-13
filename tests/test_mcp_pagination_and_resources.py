"""
End-to-End FastMCP Verification for Tool Documentation Schemas, Bounded Pagination,
Line/Snippet Truncation, Handler Modularity, and Granular Repository Resource Templates.
"""

import json
import pytest
from pydantic import AnyUrl
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

import app.services.database as db_mod
import app.services.database.connection as conn_mod
import app.services.local_storage as ls_mod
import app.services.search as search_mod
import app.services.vector_store as vs_mod
from app.services.auth import AuthContext, Role, set_current_auth_context
from app.services.database import create_adr, get_db_connection, get_db_engine, init_db
from app.services.file_reader import reset_file_reader_service
from app.services.local_storage import LocalStorageService
from app.services.vector_store.base import VectorDocument
from app.services.vector_store.manager import VectorStoreManager
from app.services.vector_store.qdrant_store import QdrantVectorStore
from app.mcp.tools import register_mcp_tools_and_resources


async def _call_tool_json(server: FastMCP, tool_name: str, **kwargs) -> dict:
    contents, _ = await server.call_tool(tool_name, kwargs)
    assert contents and hasattr(contents[0], "text")
    return json.loads(contents[0].text)


async def _read_resource_json(server: FastMCP, uri: str) -> dict:
    contents = await server.read_resource(AnyUrl(uri))
    assert contents and contents[0].content
    return json.loads(contents[0].content)


@pytest.fixture
def mcp_paginated_env(tmp_path, monkeypatch):
    """Creates an isolated real SQLite + in-memory Qdrant workspace with a fresh FastMCP server."""
    db_file = str(tmp_path / "pagination_e2e.db")
    storage_dir = tmp_path / "storage"
    repo_dir = tmp_path / "repos" / "fleet-svc"
    storage_dir.mkdir(parents=True)
    repo_dir.mkdir(parents=True)

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("CACHE_DB_PATH", db_file)
    monkeypatch.setenv("LOCAL_STORAGE_PATH", str(storage_dir))
    monkeypatch.setattr(db_mod, "CACHE_DB_PATH", db_file)
    monkeypatch.setattr(conn_mod, "CACHE_DB_PATH", db_file)

    engine = get_db_engine(f"sqlite:///{db_file}", reset=True)
    init_db(engine=engine)
    set_current_auth_context(AuthContext(role=Role.ADMIN))

    storage_svc = LocalStorageService(storage_root=str(storage_dir))
    monkeypatch.setattr(ls_mod, "_storage_service", storage_svc)
    reset_file_reader_service()

    qdrant_store = QdrantVectorStore(storage_path=":memory:", collection_name="mcp_pagination_rag", prefer_remote=False)
    monkeypatch.setattr(vs_mod, "get_vector_store", lambda: qdrant_store)
    monkeypatch.setattr(search_mod, "get_vector_store", lambda: qdrant_store)
    monkeypatch.setattr(VectorStoreManager, "get_vector_store", classmethod(lambda cls, force_reload=False: qdrant_store))

    long_literal = "X" * 520
    long_context = "Y" * 480
    (repo_dir / "grep_sample.py").write_text(
        f"# ctx {long_context}\n"
        f"GREP_TOKEN_ALPHA = '{long_literal}'\n"
        "GREP_TOKEN_BETA = 'short_1'\n"
        "GREP_TOKEN_GAMMA = 'short_2'\n"
        "GREP_TOKEN_DELTA = 'short_3'\n",
        encoding="utf-8",
    )
    (repo_dir / "seven_lines.py").write_text("\n".join(f"line_{idx}" for idx in range(1, 8)) + "\n", encoding="utf-8")
    for note in ("notes/a.md", "notes/b.md", "notes/c.md"):
        storage_svc.save_file_content(note, f"# {note}")

    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO git_repositories
               (name, url, branch, commit_sha, provider, status, keep_shallow, retain_commits_count, last_synced)
               VALUES ('fleet-svc', 'https://github.com/org/fleet-svc.git', 'main', 'deadbeef12345678', 'github', 'synced', 1, 25, '2026-11-12T00:00:00Z')"""
        )
        conn.execute(
            "INSERT INTO indexed_paths (path, type, recursive, enabled, category, repo) VALUES (?, 'directory', 1, 1, 'code', 'fleet-svc')",
            (str(repo_dir),),
        )
        file_rows = [(f"fleet-svc://src/mod_{i:03d}.py", "fleet-svc", "code", "python") for i in range(120)] + [
            (f"fleet-svc://docs/doc_{i:02d}.md", "fleet-svc", "doc", "markdown") for i in range(5)
        ]
        conn.executemany("INSERT INTO indexed_files (filepath, repo, doc_type, language) VALUES (?, ?, ?, ?)", file_rows)

        sym_rows = [
            ("fleet-svc", "fleet-svc://src/mod_000.py", f"worker_step_{i}", f"FleetEngine.worker_step_{i}", "method", i * 10 + 1, i * 10 + 8, f"def worker_step_{i}(ctx):", "python")
            for i in range(8)
        ] + [("fleet-svc", "fleet-svc://src/hub.py", "dispatch_hub", "dispatch_hub", "function", 1, 12, "def dispatch_hub():", "python")]
        conn.executemany(
            "INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            sym_rows,
        )

        rel_rows = [("fleet-svc", "src/callers.py", f"caller_fn_{i}", "dispatch_hub", "CALLS", i + 1) for i in range(5)] + [
            ("fleet-svc", "src/hub.py", "dispatch_hub", f"FleetEngine.worker_step_{i}", "CALLS", 20 + i) for i in range(4)
        ]
        conn.executemany(
            "INSERT INTO ast_relationships (repo, source_filepath, source_symbol, target_symbol, relationship_type, line_number) VALUES (?, ?, ?, ?, ?, ?)",
            rel_rows,
        )

        route_rows = [
            ("fleet-svc", f"fleet-svc://app/routes/r_{i:02d}.py", "FastAPI", "GET", f"/api/v1/vehicles/{i:02d}", f"get_vehicle_{i:02d}", 10, 20)
            for i in range(62)
        ] + [("fleet-svc", "fleet-svc://tests/test_routes.py", "FastAPI", "GET", "/api/v1/fake_test", "fake", 1, 5)]
        conn.executemany(
            "INSERT INTO api_routes (repo, filepath, framework, http_method, path_pattern, handler_symbol, start_line, end_line) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            route_rows,
        )

        caller_rows = [("web-ui", f"src/views/view_{i}.tsx", "GET", "/api/v1/vehicles/01", f"loadVehicle_{i}", 15 + i) for i in range(5)]
        conn.executemany(
            "INSERT INTO api_client_calls (repo, filepath, http_method, url_pattern, caller_symbol, line_number) VALUES (?, ?, ?, ?, ?, ?)",
            caller_rows,
        )

        many_files = [f"src/mod_{i:03d}.py" for i in range(32)]
        commit_rows = [
            ("fleet-svc", "1111111111111111", "Alice", "2026-11-12T03:00:00Z", "feat: bulk refactor", json.dumps(many_files)),
            ("fleet-svc", "2222222222222222", "Bob", "2026-11-12T02:00:00Z", "fix: step 0", json.dumps(["src/mod_000.py"])),
            ("fleet-svc", "3333333333333333", "Carol", "2026-11-12T01:00:00Z", "docs: update", json.dumps(["docs/doc_00.md"])),
        ]
        conn.executemany(
            "INSERT INTO git_commits (repo, commit_sha, author, committed_at, message, files_changed) VALUES (?, ?, ?, ?, ?, ?)",
            commit_rows,
        )
        conn.commit()

    for idx in range(4):
        create_adr(
            repo="fleet-svc",
            adr_id=f"ADR-{idx + 1:03d}",
            title=f"Telemetry Architecture Pattern {idx + 1}",
            status="ACCEPTED" if idx < 3 else "PROPOSED",
            context="High-frequency vehicle telemetry ingestion.",
            decision=f"Adopt bounded stream batching variant {idx + 1}.",
        )

    long_code = "def compute_telemetry_window(points):\n" + ("    total_value = sum(points)  # telemetry calculation\n" * 20)
    long_doc = "# Telemetry Runbook\n" + ("Telemetry stream recovery procedure step details for operators.\n" * 20)
    docs = [
        VectorDocument(
            id=f"code-{i}", text=long_code, repo="fleet-svc", doc_type="code", language="python",
            path=f"src/telemetry_{i}.py", rel_path=f"src/telemetry_{i}.py", symbol=f"compute_telemetry_window_{i}", start_line=1, end_line=22,
        )
        for i in range(3)
    ] + [
        VectorDocument(
            id=f"doc-{i}", text=long_doc, repo="fleet-svc", doc_type="doc",
            path=f"docs/telemetry_{i}.md", rel_path=f"docs/telemetry_{i}.md", heading=f"Telemetry Section {i}", start_line=1, end_line=22,
        )
        for i in range(3)
    ]
    qdrant_store.upsert_documents(docs)

    server = FastMCP("TestContextCortex", transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))
    register_mcp_tools_and_resources(server)

    yield {"server": server, "repo_dir": repo_dir}

    set_current_auth_context(None)
    get_db_engine(reset=True)


@pytest.mark.asyncio
async def test_all_10_default_mcp_tools_have_rich_schemas_and_write_tool_gating(mcp_paginated_env, monkeypatch):
    """Verifies the 10 default MCP tools (11 with MCP_ENABLE_WRITE_TOOLS=true) expose rich descriptions and Field docs."""
    from app.mcp.handlers.file_handlers import handle_grep_code as grep_from_files
    from app.mcp.handlers.grep_handlers import handle_grep_code as grep_direct
    from app.mcp.handlers.repo_handlers import handle_catalog_summary as cat_from_repo
    from app.mcp.handlers.resource_handlers import handle_catalog_summary as cat_direct

    assert grep_from_files is grep_direct
    assert cat_from_repo is cat_direct

    server = mcp_paginated_env["server"]
    tools = await server.list_tools()
    tool_names = {t.name for t in tools}
    assert tool_names == {
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

    for tool in tools:
        assert tool.description and len(tool.description.strip()) >= 40, f"Weak description on {tool.name}"
        props = (tool.inputSchema or {}).get("properties", {})
        for param_name, param_schema in props.items():
            assert param_schema.get("description"), f"Missing Field description on {tool.name}.{param_name}"

    monkeypatch.setenv("MCP_ENABLE_WRITE_TOOLS", "true")
    write_server = FastMCP("WriteEnabled", transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))
    register_mcp_tools_and_resources(write_server)
    write_tools = await write_server.list_tools()
    assert len(write_tools) == 11
    assert "manage" in {t.name for t in write_tools}


@pytest.mark.asyncio
async def test_symbol_outline_trace_and_route_pagination(mcp_paginated_env):
    """Verifies limit clamping and offset pagination across find_symbol, read_file(outline_only=True), trace_path, and find_routes."""
    server = mcp_paginated_env["server"]

    sym_p1 = await _call_tool_json(server, "find_symbol", name="worker_step_", exact=False, repo="fleet-svc", limit=3, offset=0)
    assert sym_p1["total"] == 8 and sym_p1["limit"] == 3 and len(sym_p1["symbols"]) == 3
    assert sym_p1["has_more"] is True and sym_p1["next_offset"] == 3

    sym_clamp = await _call_tool_json(server, "find_symbol", name="worker_step_", exact=False, limit=999, offset=6)
    assert sym_clamp["limit"] == 100 and len(sym_clamp["symbols"]) == 2
    assert sym_clamp["has_more"] is False and sym_clamp["next_offset"] is None

    out_p1 = await _call_tool_json(server, "read_file", path="src/mod_000.py", repo="fleet-svc", outline_only=True, limit=5, offset=0)
    assert out_p1["outline_only"] is True
    assert out_p1["total_symbols"] == 8 and len(out_p1["symbols"]) == 5
    assert out_p1["has_more"] is True and out_p1["next_offset"] == 5

    out_p2 = await _call_tool_json(server, "read_file", path="src/mod_000.py", repo="fleet-svc", outline_only=True, limit=999, offset=5)
    assert out_p2["limit"] == 500 and len(out_p2["symbols"]) == 3
    assert out_p2["has_more"] is False and out_p2["next_offset"] is None

    tr_p1 = await _call_tool_json(server, "trace_path", symbol="dispatch_hub", repo="fleet-svc", direction="both", limit=2, offset=0)
    assert tr_p1["total_callers"] == 5 and tr_p1["total_callees"] == 4
    assert len(tr_p1["callers"]) == 2 and len(tr_p1["callees"]) == 2
    assert tr_p1["has_more"] is True and tr_p1["next_offset"] == 2

    tr_p3 = await _call_tool_json(server, "trace_path", symbol="dispatch_hub", repo="fleet-svc", direction="both", limit=500, offset=4)
    assert tr_p3["limit"] == 200 and len(tr_p3["callers"]) == 1 and len(tr_p3["callees"]) == 0
    assert tr_p3["has_more"] is False

    rt_p1 = await _call_tool_json(server, "find_routes", kind="handlers", repo="fleet-svc", limit=25, offset=0)
    assert rt_p1["total"] == 62 and len(rt_p1["routes"]) == 25
    assert rt_p1["has_more"] is True and rt_p1["next_offset"] == 25

    ac_p1 = await _call_tool_json(server, "find_routes", query="/api/v1/vehicles/{id}", kind="callers", method="GET", limit=2, offset=0)
    assert ac_p1["total"] == 5 and len(ac_p1["callers"]) == 2
    assert ac_p1["has_more"] is True and ac_p1["next_offset"] == 2


@pytest.mark.asyncio
async def test_grep_search_list_repositories_and_read_file_bounds(mcp_paginated_env):
    """Verifies line/snippet truncation and pagination for grep_code, search, list_repositories, and read_file."""
    server = mcp_paginated_env["server"]

    grep_p1 = await _call_tool_json(server, "grep_code", pattern="GREP_TOKEN_", repo="fleet-svc", context_lines=1, limit=2, offset=0)
    assert grep_p1["total_matches"] == 4 and len(grep_p1["matches"]) == 2
    assert grep_p1["has_more"] is True and grep_p1["next_offset"] == 2
    first_match = grep_p1["matches"][0]
    assert len(first_match["match_text"]) <= 400 and first_match["match_text"].endswith("...[line truncated]")
    assert any(c["text"].endswith("...[line truncated]") and len(c["text"]) <= 400 for c in first_match["context"])

    grep_p2 = await _call_tool_json(server, "grep_code", pattern="GREP_TOKEN_", repo="fleet-svc", limit=2, offset=2)
    assert len(grep_p2["matches"]) == 2 and grep_p2["has_more"] is False and grep_p2["next_offset"] is None

    sc = await _call_tool_json(server, "search", query="compute_telemetry_window", scope="code", repo="fleet-svc", mode="keyword", limit=99, offset=0, max_snippet_chars=240)
    assert sc["limit"] == 25 and sc["max_snippet_chars"] == 240 and len(sc["results"]) >= 1
    assert sc["results"][0]["content_truncated"] is True
    assert len(sc["results"][0]["content"]) <= 240 and sc["results"][0]["content"].endswith("...[snippet truncated]")

    sd = await _call_tool_json(server, "search", query="Telemetry stream recovery", scope="docs", repo="fleet-svc", mode="hybrid", limit=1, offset=0, max_snippet_chars=220)
    assert sd["limit"] == 1 and sd["has_more"] is True and sd["next_offset"] == 1
    assert sd["results"][0]["content_truncated"] is True

    ing = await _call_tool_json(server, "list_repositories", source_type="all", include_files=True, include_status=True, limit=10, offset=0)
    assert ing["total_files"] == 125 and ing["has_more"] is True and ing["next_offset"] == 10
    assert "vector_store" in ing and "counts" in ing
    git_src = ing["git_repositories"][0]
    assert git_src["total_files"] == 125 and len(git_src["file_paths"]) == 10 and git_src["has_more"] is True and git_src["next_offset"] == 10
    assert ing["local_storage"]["total_files"] == 3 and ing["local_storage"]["has_more"] is False

    rf1 = await _call_tool_json(server, "read_file", path="seven_lines.py", repo="fleet-svc", start_line=2, end_line=4)
    assert rf1["total_lines"] == 7 and rf1["start_line"] == 2 and rf1["end_line"] == 4
    assert rf1["has_more"] is True and rf1["next_start_line"] == 5

    rf2 = await _call_tool_json(server, "read_file", path="seven_lines.py", repo="fleet-svc", start_line=rf1["next_start_line"])
    assert rf2["start_line"] == 5 and rf2["end_line"] == 7
    assert rf2["has_more"] is False and rf2["next_start_line"] is None


@pytest.mark.asyncio
async def test_granular_mcp_resources_and_paginated_templates(mcp_paginated_env):
    """Verifies compact catalog summary and all 5 per-repository MCP resource templates end-to-end."""
    server = mcp_paginated_env["server"]

    templates = await server.list_resource_templates()
    tpl_uris = {str(t.uriTemplate) for t in templates}
    expected_templates = {
        "knowledge://repo/{repo}/summary",
        "knowledge://repo/{repo}/architecture",
        "knowledge://repo/{repo}/files/{page}",
        "knowledge://repo/{repo}/routes/{page}",
        "knowledge://repo/{repo}/adrs",
    }
    assert expected_templates.issubset(tpl_uris)

    catalog = await _read_resource_json(server, "knowledge://catalog/summary")
    assert catalog["total_files"] == 125 and len(catalog["files"]) <= 40 and catalog["truncated_files"] == 85
    assert {t["uri_template"] for t in catalog["resource_templates"]} == expected_templates

    summary = await _read_resource_json(server, "knowledge://repo/fleet-svc/summary")
    assert summary["repo"] == "fleet-svc" and summary["status"] == "synced" and summary["commit_sha"] == "deadbeef12345678"
    assert summary["file_count"] == 125 and summary["languages"]["python"] == 120
    assert summary["symbol_count"] == 9 and summary["route_count"] == 62 and summary["adr_count"] == 4
    assert summary["sub_resources"]["files_page_1"] == "knowledge://repo/fleet-svc/files/1"

    arch = await _read_resource_json(server, "knowledge://repo/fleet-svc/architecture")
    assert arch["repo"] == "fleet-svc" and arch["total_files"] == 125

    files_p1 = await _read_resource_json(server, "knowledge://repo/fleet-svc/files/1")
    assert files_p1["page"] == 1 and files_p1["total_files"] == 125 and files_p1["total_pages"] == 2
    assert len(files_p1["files"]) == 100 and files_p1["has_more"] is True
    assert files_p1["next_uri"] == "knowledge://repo/fleet-svc/files/2"

    files_p2 = await _read_resource_json(server, files_p1["next_uri"])
    assert files_p2["page"] == 2 and len(files_p2["files"]) == 25 and files_p2["has_more"] is False and files_p2["next_uri"] is None

    routes_p1 = await _read_resource_json(server, "knowledge://repo/fleet-svc/routes/1")
    assert routes_p1["total_routes"] == 62 and routes_p1["total_pages"] == 2 and len(routes_p1["routes"]) == 50
    assert routes_p1["has_more"] is True and routes_p1["next_uri"] == "knowledge://repo/fleet-svc/routes/2"

    routes_p2 = await _read_resource_json(server, routes_p1["next_uri"])
    assert len(routes_p2["routes"]) == 12 and routes_p2["has_more"] is False and routes_p2["next_uri"] is None

    adrs_res = await _read_resource_json(server, "knowledge://repo/fleet-svc/adrs")
    assert adrs_res["repo"] == "fleet-svc" and adrs_res["total_adrs"] == 4 and len(adrs_res["adrs"]) == 4
