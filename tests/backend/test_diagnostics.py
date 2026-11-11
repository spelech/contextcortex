import json
import pytest
from unittest.mock import patch, MagicMock

from app.services.diagnostics import (
    parse_stack_frames,
    extract_diagnostic_signals,
    diagnose_issue,
    resolve_stack_frames,
    match_routes_and_callers,
    match_symbols_and_exceptions,
)
from app.mcp.handlers.diagnostic_handlers import handle_diagnose_issue
from app.mcp.mcp_server import mcp_server


def test_parse_stack_frames_python():
    trace = """
Traceback (most recent call last):
  File "app/services/jwt_validator.py", line 84, in verify_token
    payload = jwt.decode(token, key)
ValueError: Invalid token
    """
    frames = parse_stack_frames(trace)
    assert len(frames) == 1
    assert frames[0]["path"] == "app/services/jwt_validator.py"
    assert frames[0]["line"] == 84
    assert frames[0]["function"] == "verify_token"


def test_parse_stack_frames_typescript_node():
    trace = """
Error: Network timeout
    at submitCheckout (src/api/checkout.ts:44:12)
    at Object.run (/app/node_modules/runner/index.js:123:45)
    """
    frames = parse_stack_frames(trace)
    assert len(frames) == 2
    assert frames[0]["path"] == "src/api/checkout.ts"
    assert frames[0]["line"] == 44
    assert frames[0]["function"] == "submitCheckout"
    assert "runner/index.js" in frames[1]["path"]
    assert frames[1]["line"] == 123


def test_parse_stack_frames_csharp():
    trace = """
System.NullReferenceException: Object reference not set to an instance of an object.
   in Core/Controllers/OrderController.cs:line 123
   in System.Web.Mvc.ControllerActionInvoker.InvokeAction()
    """
    frames = parse_stack_frames(trace)
    assert len(frames) == 1
    assert frames[0]["path"] == "Core/Controllers/OrderController.cs"
    assert frames[0]["line"] == 123


def test_parse_stack_frames_java():
    trace = """
java.lang.NullPointerException
    at com.example.service.OrderService.processPayment(OrderService.java:123)
    at com.example.api.ApiController.checkout(ApiController.java:45)
    """
    frames = parse_stack_frames(trace)
    assert len(frames) == 2
    assert frames[0]["path"] == "OrderService.java"
    assert frames[0]["line"] == 123
    assert "processPayment" in frames[0]["function"]
    assert frames[1]["path"] == "ApiController.java"
    assert frames[1]["line"] == 45


def test_parse_stack_frames_go_rust():
    trace = """
panic: runtime error: invalid memory address or nil pointer dereference
[signal SIGSEGV: code=0x1 addr=0x0 pc=0x12345]
goroutine 1 [running]:
main.processItem(0x0, 0x0)
    server/handlers/checkout.go:88 +0x2b
thread 'main' panicked at 'index out of bounds', src/parser/lexer.rs:105:9
    """
    frames = parse_stack_frames(trace)
    paths = [f["path"] for f in frames]
    assert any("checkout.go" in p for p in paths)
    assert any("lexer.rs" in p for p in paths)
    go_frame = next(f for f in frames if "checkout.go" in f["path"])
    assert go_frame["line"] == 88
    rust_frame = next(f for f in frames if "lexer.rs" in f["path"])
    assert rust_frame["line"] == 105


def test_extract_diagnostic_signals():
    text = """
2026-03-30T10:15:00 ERROR [auth-service] Request failed with "Invalid authorization credentials provided"
POST /api/v1/checkout HTTP/1.1 returned 500
Caused by InvalidTokenError: Token has expired
    """
    signals = extract_diagnostic_signals(text)
    assert "Invalid authorization credentials provided" in signals["quoted_errors"]
    assert "InvalidTokenError" in signals["exceptions"]
    route_paths = [r[1] for r in signals["routes"]]
    assert "/api/v1/checkout" in route_paths


def test_resolve_stack_frames_with_db():
    frames = [{"path": "app/services/jwt_validator.py", "line": 84, "function": "verify_token"}]
    with patch("app.services.diagnostics.get_db_connection") as mock_conn, \
         patch("app.services.diagnostics.get_file_reader_service") as mock_fr:

        mock_db = MagicMock()
        mock_conn.return_value.__enter__.return_value = mock_db

        mock_db.execute.return_value.fetchall.side_effect = [
            # git_repositories
            [{"name": "auth-service", "url": "https://github.com/org/auth-service", "commit_sha": "abc1234", "provider": "github"}],
            # callers
            [{"repo": "auth-service", "source_symbol": "auth_middleware", "source_filepath": "app/middleware.py", "line_number": 29}],
            # callees
            []
        ]
        # indexed_files lookup then ast_symbols enclosing lookup
        mock_db.execute.return_value.fetchone.side_effect = [
            {"filepath": "app/services/jwt_validator.py", "repo": "auth-service", "doc_type": "code", "language": "python", "commit_sha": "abc1234"},
            {"id": 1, "repo": "auth-service", "filepath": "app/services/jwt_validator.py", "name": "verify_token", "full_symbol": "JWTValidator.verify_token", "kind": "method", "signature": "def verify_token(self, token: str) -> dict", "start_line": 80, "end_line": 100}
        ]

        mock_reader = MagicMock()
        mock_reader.read_file.return_value = {"content": "def verify_token():\n    pass"}
        mock_fr.return_value = mock_reader

        resolved = resolve_stack_frames(frames, repo="auth-service", context_lines=5)
        assert len(resolved) == 1
        f = resolved[0]
        assert f["repo"] == "auth-service"
        assert f["file"] == "app/services/jwt_validator.py"
        assert f["symbol"] == "JWTValidator.verify_token"
        assert f["kind"] == "method"
        assert f["signature"] == "def verify_token(self, token: str) -> dict"
        assert "def verify_token" in f["code"]
        assert len(f["callers"]) == 1
        assert f["callers"][0]["symbol"] == "auth_middleware"
        assert f["permalink"] is not None
        assert "auth-service/blob/abc1234/app/services/jwt_validator.py#L84" in f["permalink"]


def test_match_routes_and_callers():
    extracted_routes = [("POST", "/api/v1/checkout")]
    with patch("app.services.diagnostics.get_db_connection") as mock_conn:
        mock_db = MagicMock()
        mock_conn.return_value.__enter__.return_value = mock_db

        mock_db.execute.return_value.fetchall.side_effect = [
            # api_routes
            [{
                "id": 1,
                "repo": "orders-api",
                "filepath": "app/api/routes.py",
                "http_method": "POST",
                "path_pattern": "/api/v1/checkout",
                "handler_symbol": "checkout_endpoint",
                "start_line": 31,
                "end_line": 50
            }],
            # api_client_calls
            [{
                "id": 2,
                "repo": "web-frontend",
                "filepath": "src/api/checkout.ts",
                "http_method": "POST",
                "url_pattern": "/api/v1/checkout",
                "caller_symbol": "submitCheckout",
                "line_number": 44
            }]
        ]

        matches = match_routes_and_callers(extracted_routes)
        assert len(matches) == 1
        m = matches[0]
        assert m["method"] == "POST"
        assert m["path"] == "/api/v1/checkout"
        assert m["handler"]["symbol"] == "checkout_endpoint"
        assert len(m["external_callers"]) == 1
        assert m["external_callers"][0]["symbol"] == "submitCheckout"


def test_match_symbols_and_exceptions():
    with patch("app.services.diagnostics.get_db_connection") as mock_conn:
        mock_db = MagicMock()
        mock_conn.return_value.__enter__.return_value = mock_db
        mock_db.execute.return_value.fetchall.return_value = [
            {
                "repo": "auth-service",
                "name": "InvalidTokenError",
                "full_symbol": "InvalidTokenError",
                "kind": "class",
                "filepath": "app/exceptions.py",
                "start_line": 10,
                "end_line": 18
            }
        ]

        res = match_symbols_and_exceptions(exceptions=["InvalidTokenError"], quoted_errors=[])
        assert len(res) == 1
        assert res[0]["symbol"] == "InvalidTokenError"
        assert res[0]["kind"] == "class"
        assert res[0]["lines"] == [10, 18]


def test_diagnose_issue_natural_language():
    """Verifies diagnose_issue functions on natural-language user reports without stack frames."""
    user_report = "Users are getting HTTP 500 when clicking checkout button on cart page with empty inventory"

    mock_hit = MagicMock()
    mock_hit.score = 0.8912
    mock_hit.payload = {
        "repo": "orders-api",
        "rel_path": "app/services/orders.py",
        "start_line": 45,
        "end_line": 88,
        "symbol": "OrderService.create_order",
        "full_symbol": "OrderService.create_order",
        "kind": "method",
        "signature": "async def create_order(cart_id: str, user_id: str)",
        "content": "async def create_order(): ...",
        "permalink_url": "https://github.com/org/orders-api/blob/main/app/services/orders.py#L45-L88"
    }

    with patch("app.services.diagnostics.execute_hybrid_search", return_value=[mock_hit]), \
         patch("app.services.diagnostics.get_db_connection") as mock_conn:

        mock_db = MagicMock()
        mock_conn.return_value.__enter__.return_value = mock_db
        # git_repositories, callers, callees, api_routes, api_calls, ast_symbols
        mock_db.execute.return_value.fetchall.return_value = []

        result = diagnose_issue(user_report)
        assert "resolved_frames" in result
        assert len(result["resolved_frames"]) == 0
        assert "semantic_candidates" in result
        assert len(result["semantic_candidates"]) == 1
        c = result["semantic_candidates"][0]
        assert c["symbol"] == "OrderService.create_order"
        assert c["score"] == 0.8912
        assert c["repo"] == "orders-api"
        assert c["lines"] == [45, 88]


@pytest.mark.asyncio
async def test_handle_diagnose_issue_mcp():
    payload = await handle_diagnose_issue("TypeError: cannot read property 'id' of undefined at user.js:10")
    data = json.loads(payload)
    assert "resolved_frames" in data
    assert "matched_routes" in data
    assert "matched_symbols" in data
    assert "semantic_candidates" in data


@pytest.mark.asyncio
async def test_diagnose_issue_registered_on_mcp_server():
    tools = await mcp_server.list_tools()
    tool_names = [t.name for t in tools]
    assert "diagnose_issue" in tool_names
