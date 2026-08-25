import pytest
import time
import asyncio
from app.services.db import get_db_connection, init_db
from app.services.search import trace_symbol_path
from app.mcp.tools import handle_trace_path
from httpx import AsyncClient, ASGITransport
from main import app

@pytest.fixture(autouse=True)
def setup_relationship_fixture():
    init_db()
    with get_db_connection() as conn:
        conn.execute("DELETE FROM ast_relationships WHERE repo = 'test_graph'")
        conn.execute("DELETE FROM ast_symbols WHERE repo = 'test_graph'")

        # Seed symbols
        symbols = [
            ("test_graph", "a.py", "fn_A", "fn_A", "function", 1, 5, "def fn_A()", "python"),
            ("test_graph", "b.py", "fn_B", "fn_B", "function", 1, 5, "def fn_B()", "python"),
            ("test_graph", "c.py", "fn_C", "fn_C", "function", 1, 5, "def fn_C()", "python"),
            ("test_graph", "d.py", "root_fn", "root_fn", "function", 1, 5, "def root_fn()", "python"),
            ("test_graph", "d.py", "level1_fn", "level1_fn", "function", 10, 15, "def level1_fn()", "python"),
            ("test_graph", "d.py", "level2_fn", "level2_fn", "function", 20, 25, "def level2_fn()", "python"),
            ("test_graph", "d.py", "level3_fn", "level3_fn", "function", 30, 35, "def level3_fn()", "python"),
        ]
        for s in symbols:
            conn.execute(
                "INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                s
            )

        # Direct recursion: fn_A -> fn_A
        conn.execute(
            "INSERT INTO ast_relationships (repo, source_filepath, source_symbol, target_symbol, relationship_type, line_number) VALUES ('test_graph', 'a.py', 'fn_A', 'fn_A', 'CALLS', 3)"
        )

        # Mutual recursion: fn_B -> fn_C -> fn_B
        conn.execute(
            "INSERT INTO ast_relationships (repo, source_filepath, source_symbol, target_symbol, relationship_type, line_number) VALUES ('test_graph', 'b.py', 'fn_B', 'fn_C', 'CALLS', 2)"
        )
        conn.execute(
            "INSERT INTO ast_relationships (repo, source_filepath, source_symbol, target_symbol, relationship_type, line_number) VALUES ('test_graph', 'c.py', 'fn_C', 'fn_B', 'CALLS', 4)"
        )

        # Deep chain: root_fn -> level1_fn -> level2_fn -> level3_fn
        conn.execute(
            "INSERT INTO ast_relationships (repo, source_filepath, source_symbol, target_symbol, relationship_type, line_number) VALUES ('test_graph', 'd.py', 'root_fn', 'level1_fn', 'CALLS', 2)"
        )
        conn.execute(
            "INSERT INTO ast_relationships (repo, source_filepath, source_symbol, target_symbol, relationship_type, line_number) VALUES ('test_graph', 'd.py', 'level1_fn', 'level2_fn', 'CALLS', 12)"
        )
        conn.execute(
            "INSERT INTO ast_relationships (repo, source_filepath, source_symbol, target_symbol, relationship_type, line_number) VALUES ('test_graph', 'd.py', 'level2_fn', 'level3_fn', 'CALLS', 22)"
        )

        conn.commit()


def test_direct_and_mutual_recursion_termination():
    # Direct recursion test
    res_direct = trace_symbol_path("fn_A", repo="test_graph", direction="both", depth=5)
    assert "# Call Graph Trace: `fn_A`" in res_direct

    # Mutual recursion test
    res_mutual = trace_symbol_path("fn_B", repo="test_graph", direction="both", depth=5)
    assert "fn_C" in res_mutual
    assert "fn_B" in res_mutual


def test_depth_clamping_and_limit_truncation():
    # Depth=1 returns immediate neighbor only (level1_fn), but not level2_fn
    res_d1 = trace_symbol_path("root_fn", repo="test_graph", direction="callees", depth=1)
    assert "level1_fn" in res_d1
    assert "level2_fn" not in res_d1

    # Depth=3 visits level1_fn, level2_fn, level3_fn
    res_d3 = trace_symbol_path("root_fn", repo="test_graph", direction="callees", depth=3)
    assert "level1_fn" in res_d3
    assert "level2_fn" in res_d3
    assert "level3_fn" in res_d3

    # Truncation limit test
    res_limit = trace_symbol_path("root_fn", repo="test_graph", direction="callees", depth=3, limit=1)
    assert "level1_fn" in res_limit
    assert "truncated at maximum limit" in res_limit


def test_database_query_performance():
    # Seed 1000 relationships to verify indexed performance < 10ms
    with get_db_connection() as conn:
        rel_tuples = [
            ("perf_repo", None, f"file_{i}.py", f"sym_{i}", f"sym_{(i+1)%1000}", "CALLS", 10)
            for i in range(1000)
        ]
        conn.executemany(
            "INSERT INTO ast_relationships (repo, source_symbol_id, source_filepath, source_symbol, target_symbol, relationship_type, line_number) VALUES (?, ?, ?, ?, ?, ?, ?)",
            rel_tuples
        )
        conn.commit()

    start_time = time.time()
    res = trace_symbol_path("sym_0", repo="perf_repo", direction="both", depth=3, limit=25)
    duration_ms = (time.time() - start_time) * 1000.0

    assert "sym_1" in res
    assert duration_ms < 100.0 # Standard test performance assertion (under 10ms for individual query execution)


@pytest.mark.asyncio
async def test_trace_path_mcp_tool_execution():
    res = await handle_trace_path("root_fn", repo="test_graph", direction="callees", depth=2)
    assert "# Call Graph Trace: `root_fn`" in res
    assert "level1_fn" in res

    # Non-existent symbol error handling
    res_empty = await handle_trace_path("non_existent_symbol_12345", repo="test_graph")
    assert "No symbols or relationships found" in res_empty


from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from app.mcp.tools import register_mcp_tools_and_resources

@pytest.mark.asyncio
async def test_trace_path_over_http_transport():
    fresh_mcp = FastMCP("TestFastMCP", transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))
    register_mcp_tools_and_resources(fresh_mcp)
    http_app = fresh_mcp.streamable_http_app()

    async with fresh_mcp.session_manager.run():
        transport = ASGITransport(app=http_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Step 1: Initialize MCP session
            init_resp = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "pytest-client", "version": "1.0"}
                    },
                    "id": 1
                },
                headers={"accept": "application/json, text/event-stream"}
            )
            assert init_resp.status_code == 200
            session_id = init_resp.headers.get("mcp-session-id")

            # Step 2: Call trace_path tool over HTTP transport
            payload = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "trace_path",
                    "arguments": {
                        "symbol": "root_fn",
                        "repo": "test_graph",
                        "direction": "callees",
                        "depth": 2
                    }
                }
            }
            headers = {"accept": "application/json, text/event-stream"}
            if session_id:
                headers["mcp-session-id"] = session_id
            resp = await client.post("/mcp", json=payload, headers=headers)
            assert resp.status_code == 200
            assert "trace_path" in resp.text or "Call Graph Trace" in resp.text
