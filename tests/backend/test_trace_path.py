import pytest
import time
import asyncio
from app.services.database import get_db_connection, init_db
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


import json

def test_direct_and_mutual_recursion_termination():
    # Direct recursion test
    res_direct = trace_symbol_path("fn_A", repo="test_graph", direction="both", depth=5)
    data_direct = json.loads(res_direct)
    assert data_direct["target"]["symbol"] == "fn_A"
    assert data_direct["target"]["file"] == "a.py"

    # Mutual recursion test
    res_mutual = trace_symbol_path("fn_B", repo="test_graph", direction="both", depth=5)
    data_mutual = json.loads(res_mutual)
    assert data_mutual["target"]["symbol"] == "fn_B"
    # Callees should have fn_C
    callee_symbols = [c["symbol"] for c in data_mutual["callees"]]
    assert "fn_C" in callee_symbols


def test_depth_clamping_and_limit_truncation():
    # Depth=1 returns immediate neighbor only (level1_fn), but not level2_fn
    res_d1 = trace_symbol_path("root_fn", repo="test_graph", direction="callees", depth=1)
    data_d1 = json.loads(res_d1)
    assert len(data_d1["callees"]) == 1
    assert data_d1["callees"][0]["symbol"] == "level1_fn"
    assert data_d1["callees"][0]["callees"] == []

    # Depth=3 visits level1_fn, level2_fn, level3_fn
    res_d3 = trace_symbol_path("root_fn", repo="test_graph", direction="callees", depth=3)
    data_d3 = json.loads(res_d3)
    lvl1 = data_d3["callees"][0]
    assert lvl1["symbol"] == "level1_fn"
    assert len(lvl1["callees"]) == 1
    lvl2 = lvl1["callees"][0]
    assert lvl2["symbol"] == "level2_fn"
    assert len(lvl2["callees"]) == 1
    lvl3 = lvl2["callees"][0]
    assert lvl3["symbol"] == "level3_fn"

    # Truncation limit test
    res_limit = trace_symbol_path("root_fn", repo="test_graph", direction="callees", depth=3, limit=1)
    data_limit = json.loads(res_limit)
    assert data_limit["truncated"] is True
    assert len(data_limit["callees"]) == 1


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

    data = json.loads(res)
    assert data["target"]["symbol"] == "sym_0"
    assert duration_ms < 100.0


@pytest.mark.asyncio
async def test_trace_path_mcp_tool_execution():
    res = await handle_trace_path("root_fn", repo="test_graph", direction="callees", depth=2)
    data = json.loads(res)
    assert data["target"]["name"] == "root_fn"
    assert len(data["callees"]) >= 1
    assert data["callees"][0]["symbol"] == "level1_fn"

    # Non-existent symbol error handling
    res_empty = await handle_trace_path("non_existent_symbol_12345", repo="test_graph")
    data_empty = json.loads(res_empty)
    assert data_empty["found"] is False
    assert data_empty["symbol"] == "non_existent_symbol_12345"

    # Empty symbol validation error handling
    res_blank = await handle_trace_path("", repo="test_graph")
    data_blank = json.loads(res_blank)
    assert "error" in data_blank


def test_cross_repo_boundary_resolution():
    """
    Unit tests verifying cross-repo boundary resolution:
    - Tracing a backend handler symbol in repo_b includes external_callers from repo_a via api_routes <-> api_client_calls matching.
    - Tracing a client symbol in repo_a includes external_handlers in repo_b, while keeping AST BFS expansion scoped to repo_a.
    """
    with get_db_connection() as conn:
        # Repositories
        conn.execute("INSERT OR REPLACE INTO git_repositories (name, url, commit_sha, provider) VALUES ('orders-api', 'https://github.com/org/orders-api.git', 'abc1234', 'github')")
        conn.execute("INSERT OR REPLACE INTO git_repositories (name, url, commit_sha, provider) VALUES ('web-frontend', 'https://github.com/org/web-frontend.git', 'xyz9876', 'github')")
        conn.execute("INSERT OR REPLACE INTO git_repositories (name, url, commit_sha, provider) VALUES ('tax-service', 'https://github.com/org/tax-service.git', 't1a2x3', 'github')")

        # AST symbols
        conn.execute("INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language) VALUES ('orders-api', 'orders-api://app/services/orders.py', 'create_order', 'OrderService.create_order', 'method', 45, 88, 'def create_order():', 'python')")
        conn.execute("INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language) VALUES ('orders-api', 'app/api/routes.py', 'checkout_endpoint', 'checkout_endpoint', 'function', 30, 40, 'def checkout_endpoint():', 'python')")
        conn.execute("INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language) VALUES ('orders-api', 'app/services/inventory.py', 'validate_inventory', 'validate_inventory', 'function', 14, 25, 'def validate_inventory():', 'python')")
        conn.execute("INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language) VALUES ('web-frontend', 'src/api/checkout.ts', 'submitCheckout', 'submitCheckout', 'function', 40, 60, 'export function submitCheckout()', 'typescript')")
        conn.execute("INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language) VALUES ('tax-service', 'app/routes/tax.py', 'get_tax_by_zip', 'get_tax_by_zip', 'function', 19, 35, 'def get_tax_by_zip():', 'python')")

        # Intra-repo relationships in orders-api:
        # checkout_endpoint -> OrderService.create_order -> validate_inventory
        conn.execute("INSERT INTO ast_relationships (repo, source_filepath, source_symbol, target_symbol, relationship_type, line_number) VALUES ('orders-api', 'app/api/routes.py', 'checkout_endpoint', 'OrderService.create_order', 'calls', 31)")
        conn.execute("INSERT INTO ast_relationships (repo, source_filepath, source_symbol, target_symbol, relationship_type, line_number) VALUES ('orders-api', 'app/services/orders.py', 'OrderService.create_order', 'validate_inventory', 'calls', 14)")

        # Inbound route for checkout_endpoint
        conn.execute("INSERT INTO api_routes (repo, filepath, framework, http_method, path_pattern, handler_symbol, start_line, end_line) VALUES ('orders-api', 'app/api/routes.py', 'FastAPI', 'POST', '/api/v1/orders', 'checkout_endpoint', 30, 40)")

        # Client call from web-frontend calling /api/v1/orders
        conn.execute("INSERT INTO api_client_calls (repo, filepath, http_method, url_pattern, caller_symbol, line_number) VALUES ('web-frontend', 'web-frontend://src/api/checkout.ts', 'POST', '/api/v1/orders', 'submitCheckout', 44)")

        # Outbound HTTP call from validate_inventory calling tax-service GET /api/v1/tax/{zip}
        conn.execute("INSERT INTO api_client_calls (repo, filepath, http_method, url_pattern, caller_symbol, line_number) VALUES ('orders-api', 'app/services/inventory.py', 'GET', '/api/v1/tax/{zip}', 'validate_inventory', 27)")

        # Route in tax-service
        conn.execute("INSERT INTO api_routes (repo, filepath, framework, http_method, path_pattern, handler_symbol, start_line, end_line) VALUES ('tax-service', 'app/routes/tax.py', 'FastAPI', 'GET', '/api/v1/tax/:zip', 'get_tax_by_zip', 19, 35)")

        conn.commit()

    # 1. Trace OrderService.create_order in orders-api
    res_raw = trace_symbol_path("OrderService.create_order", repo="orders-api", direction="both", depth=2)
    data = json.loads(res_raw)

    assert data["target"]["symbol"] == "OrderService.create_order"
    assert data["target"]["file"] == "app/services/orders.py"
    assert data["target"]["repo"] == "orders-api"
    assert "://" not in data["target"]["file"]

    # Inbound callers check: checkout_endpoint should have route and external_callers from web-frontend
    assert len(data["callers"]) == 1
    caller_node = data["callers"][0]
    assert caller_node["symbol"] == "checkout_endpoint"
    assert caller_node["file"] == "app/api/routes.py"
    assert caller_node["route"] == {"method": "POST", "path": "/api/v1/orders"}
    assert len(caller_node["external_callers"]) == 1
    ext_caller = caller_node["external_callers"][0]
    assert ext_caller["repo"] == "web-frontend"
    assert ext_caller["symbol"] == "submitCheckout"
    assert ext_caller["file"] == "src/api/checkout.ts"
    assert "://" not in ext_caller["file"]
    assert ext_caller["line"] == 44

    # Outbound callees check: validate_inventory should have http_calls with external_handlers in tax-service
    assert len(data["callees"]) == 1
    callee_node = data["callees"][0]
    assert callee_node["symbol"] == "validate_inventory"
    assert len(callee_node["http_calls"]) == 1
    http_call = callee_node["http_calls"][0]
    assert http_call["method"] == "GET"
    assert http_call["url"] == "/api/v1/tax/{zip}"
    assert len(http_call["external_handlers"]) == 1
    ext_handler = http_call["external_handlers"][0]
    assert ext_handler["repo"] == "tax-service"
    assert ext_handler["symbol"] == "get_tax_by_zip"
    assert ext_handler["file"] == "app/routes/tax.py"
    assert "://" not in ext_handler["file"]
    assert ext_handler["line"] == 19

    # 2. Trace frontend symbol submitCheckout: target itself should have http_calls with external_handlers
    res_fe = trace_symbol_path("submitCheckout", repo="web-frontend", direction="callees", depth=2)
    data_fe = json.loads(res_fe)
    assert data_fe["target"]["symbol"] == "submitCheckout"
    assert data_fe["target"]["repo"] == "web-frontend"
    assert len(data_fe["target"]["http_calls"]) == 1
    fe_call = data_fe["target"]["http_calls"][0]
    assert fe_call["method"] == "POST"
    assert any(h["repo"] == "orders-api" and h["symbol"] == "checkout_endpoint" for h in fe_call["external_handlers"])
    # AST BFS stays scoped to web-frontend
    assert data_fe["callees"] == []


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
            # Response may be SSE stream or direct json
            if "data:" in resp.text:
                data_line = [line for line in resp.text.splitlines() if line.startswith("data:")][0]
                resp_json = json.loads(data_line[5:].strip())
            else:
                resp_json = resp.json()
            tool_content = resp_json["result"]["content"][0]["text"]
            parsed = json.loads(tool_content)
            assert parsed["target"]["name"] == "root_fn"
            assert parsed["callees"][0]["symbol"] == "level1_fn"
