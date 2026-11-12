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


def test_resolve_stack_frames_with_db(tmp_path, monkeypatch):
    """Verifies stack frame resolution against a real SQLite database and real file on disk, prioritizing production callers and file-scoped callees."""
    from app.services.database import init_db, get_db_connection
    from app.services.database.engine import dispose_global_engine

    db_file = tmp_path / "diag_test.db"
    vault_dir = tmp_path / "vault"
    repo_dir = vault_dir / "repos" / "auth-service" / "app" / "services"
    repo_dir.mkdir(parents=True)
    target_py = repo_dir / "jwt_validator.py"
    lines = [f"# line {i}" for i in range(1, 79)]
    lines.extend([
        "class JWTValidator:",
        "    def verify_token(self, token: str) -> dict:",
        "        payload = decode_jwt(token)",
        "        if not payload:",
        "            raise ValueError('Invalid token')",
        "        return payload",
    ])
    lines.extend([f"# line {i}" for i in range(86, 105)])
    target_py.write_text("\n".join(lines), encoding="utf-8")

    import app.services.git_manager as gm
    monkeypatch.setattr(gm, "PERSISTENT_REPOS_DIR", str(vault_dir / "repos"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("VAULT_PATH", str(vault_dir))
    dispose_global_engine()
    init_db(str(vault_dir))

    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO git_repositories (name, url, branch, commit_sha, provider) VALUES (?, ?, ?, ?, ?)",
            ("auth-service", "https://github.com/org/auth-service", "main", "abc1234", "github"),
        )
        conn.execute(
            "INSERT INTO indexed_files (filepath, repo, hash, doc_type, language, commit_sha) VALUES (?, ?, ?, ?, ?, ?)",
            ("auth-service://app/services/jwt_validator.py", "auth-service", "h1", "code", "python", "abc1234"),
        )
        conn.execute(
            "INSERT INTO ast_symbols (id, repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, "auth-service", "auth-service://app/services/jwt_validator.py", "verify_token", "JWTValidator.verify_token", "method", 80, 85, "def verify_token(self, token: str) -> dict", "python"),
        )
        # Insert both a test caller and a production caller; production caller must rank first
        conn.execute(
            "INSERT INTO ast_relationships (repo, source_symbol_id, source_filepath, source_symbol, target_symbol, relationship_type, line_number) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("auth-service", 1, "auth-service://tests/test_auth.py", "test_verify_token", "verify_token", "CALLS", 15),
        )
        conn.execute(
            "INSERT INTO ast_relationships (repo, source_symbol_id, source_filepath, source_symbol, target_symbol, relationship_type, line_number) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("auth-service", 1, "auth-service://app/middleware.py", "auth_middleware", "JWTValidator.verify_token", "CALLS", 29),
        )
        # Insert a callee inside jwt_validator.py L80-85 and an unrelated callee with same method name in another file
        conn.execute(
            "INSERT INTO ast_relationships (repo, source_symbol_id, source_filepath, source_symbol, target_symbol, relationship_type, line_number) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("auth-service", 1, "auth-service://app/services/jwt_validator.py", "verify_token", "decode_jwt", "CALLS", 81),
        )
        conn.execute(
            "INSERT INTO ast_relationships (repo, source_symbol_id, source_filepath, source_symbol, target_symbol, relationship_type, line_number) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("auth-service", 1, "auth-service://app/services/other_validator.py", "verify_token", "unrelated_helper", "CALLS", 81),
        )

    frames = [{"path": "app/services/jwt_validator.py", "line": 84, "function": "verify_token"}]
    resolved = resolve_stack_frames(frames, repo="auth-service", context_lines=5)
    assert len(resolved) == 1
    f = resolved[0]
    assert f["repo"] == "auth-service"
    assert f["file"] == "app/services/jwt_validator.py"
    assert f["symbol"] == "JWTValidator.verify_token"
    assert f["kind"] == "method"
    assert f["signature"] == "def verify_token(self, token: str) -> dict"
    assert "def verify_token" in f["code"]
    assert f["callers"][0]["symbol"] == "auth_middleware"
    assert [c["symbol"] for c in f["callees"]] == ["decode_jwt"]
    assert f["permalink"] is not None
    assert "auth-service/blob/abc1234/app/services/jwt_validator.py#L84" in f["permalink"]
    dispose_global_engine()


def test_match_routes_and_callers(tmp_path, monkeypatch):
    """Verifies route and caller matching against a real SQLite database while excluding test routes."""
    from app.services.database import init_db, get_db_connection
    from app.services.database.engine import dispose_global_engine

    db_file = tmp_path / "routes_diag.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    dispose_global_engine()
    init_db(str(tmp_path))

    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO api_routes (repo, filepath, framework, http_method, path_pattern, handler_symbol, start_line, end_line) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("orders-api", "orders-api://app/api/routes.py", "fastapi", "POST", "/api/v1/checkout", "checkout_endpoint", 31, 50),
        )
        conn.execute(
            "INSERT INTO api_client_calls (repo, filepath, http_method, url_pattern, caller_symbol, line_number) VALUES (?, ?, ?, ?, ?, ?)",
            ("web-frontend", "web-frontend://src/api/checkout.ts", "POST", "/api/v1/checkout", "submitCheckout", 44),
        )

    matches = match_routes_and_callers([("POST", "/api/v1/checkout")])
    assert len(matches) == 1
    m = matches[0]
    assert m["method"] == "POST"
    assert m["path"] == "/api/v1/checkout"
    assert m["handler"]["symbol"] == "checkout_endpoint"
    assert len(m["external_callers"]) == 1
    assert m["external_callers"][0]["symbol"] == "submitCheckout"
    dispose_global_engine()


def test_match_symbols_and_exceptions(tmp_path, monkeypatch):
    """Verifies exception and symbol matching against a real SQLite database."""
    from app.services.database import init_db, get_db_connection
    from app.services.database.engine import dispose_global_engine

    db_file = tmp_path / "syms_diag.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    dispose_global_engine()
    init_db(str(tmp_path))

    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("auth-service", "auth-service://app/exceptions.py", "InvalidTokenError", "InvalidTokenError", "class", 10, 18, "python"),
        )
        conn.execute(
            "INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("auth-service", "auth-service://app/db.py", "get_db_engine", "get_db_engine", "function", 20, 45, "python"),
        )

    res = match_symbols_and_exceptions(
        exceptions=["InvalidTokenError"],
        quoted_errors=[],
        candidate_symbols=["get_db_engine"],
    )
    assert len(res) == 2
    assert {r["symbol"] for r in res} == {"InvalidTokenError", "get_db_engine"}
    dispose_global_engine()


def test_diagnose_issue_natural_language(tmp_path, monkeypatch):
    """Verifies diagnose_issue functions on natural-language user reports with symbol extraction and hybrid search."""
    from app.services.database import init_db, get_db_connection
    from app.services.database.engine import dispose_global_engine

    db_file = tmp_path / "nl_diag.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    dispose_global_engine()
    init_db(str(tmp_path))

    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("orders-api", "orders-api://app/services/orders.py", "create_order", "OrderService.create_order", "method", 45, 88, "python"),
        )

    user_report = "Users are getting HTTP 500 in OrderService.create_order when clicking checkout button on cart page"
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

    with patch("app.services.diagnostics.execute_hybrid_search", return_value=[mock_hit]):
        result = diagnose_issue(user_report)
        assert len(result["resolved_frames"]) == 0
        assert len(result["matched_symbols"]) == 1
        assert result["matched_symbols"][0]["symbol"] == "OrderService.create_order"
        assert len(result["semantic_candidates"]) == 1
        c = result["semantic_candidates"][0]
        assert c["symbol"] == "OrderService.create_order"
        assert c["score"] == 0.8912
        assert c["repo"] == "orders-api"
        assert c["lines"] == [45, 88]
    dispose_global_engine()


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
