"""Tools return repository-relative paths for local sources (`indexed_paths`), the same form as for git repositories."""

import asyncio
import json

import pytest

from app.mcp.handlers.route_handlers import handle_find_api_callers, handle_find_routes
from app.mcp.handlers.symbol_handlers import handle_find_symbol, handle_get_file_outline
from app.services.database import get_db_connection
from app.services.database.engine import get_db_engine, init_db
from app.services.diagnostics import (
    _get_callers_and_callees, match_routes_and_callers, match_symbols_and_exceptions, resolve_stack_frames,
)
from app.services.graph_traversal import trace_symbol_path
from app.services.source_paths import LocalSourceRoots, clean_stored_path

LOCAL_REPO = "hub-prefix"
LOCAL_ROOT = r"C:\Development\TEMP\claude\debug-eval\hub-prefix"
CONTROLLER = "server/Controllers/ToolsController.cs"
SERVICE = "server/Services/ToolService.cs"
GIT_REPO = "web-client"
CLIENT = "src/api/tools.ts"


def _local(rel: str) -> str:
    return LOCAL_ROOT + "\\" + rel.replace("/", "\\")


@pytest.mark.parametrize("filepath, repo, expected", [
    (_local(CONTROLLER), LOCAL_REPO, CONTROLLER),
    (_local(CONTROLLER).replace("\\", "/"), None, CONTROLLER),
    (_local(CONTROLLER).lower(), None, CONTROLLER.lower()),
    (f"{GIT_REPO}://{CLIENT}", GIT_REPO, CLIENT),
    (r"D:\Other\server\X.cs", None, "D:/Other/server/X.cs"),
    (LOCAL_ROOT + "-old\\server\\X.cs", None, "C:/Development/TEMP/claude/debug-eval/hub-prefix-old/server/X.cs"),
    ("", None, ""),
    (None, None, ""),
])
def test_relative_maps_stored_paths(filepath, repo, expected):
    roots = LocalSourceRoots([(LOCAL_REPO, LOCAL_ROOT)])
    assert roots.relative(filepath, repo) == expected


def test_nested_roots_use_the_longest_root_and_file_roots_use_the_file_name():
    roots = LocalSourceRoots([
        ("outer", "/srv/code"),
        ("inner", "/srv/code/inner/"),
        ("single", r"C:\notes\todo.md"),
    ])
    assert roots.relative("/srv/code/inner/a/b.py") == "a/b.py"
    assert roots.relative("/srv/code/a/b.py") == "a/b.py"
    assert roots.relative(r"C:\notes\todo.md", "single") == "todo.md"
    assert roots.strip_root("/srv/other/b.py") is None
    assert roots.strip_root("outer://a/b.py") is None


def test_clean_stored_path_keeps_the_git_form():
    assert clean_stored_path("repo://a\\b.py") == "a/b.py"
    assert clean_stored_path(r"C:\x\y.py") == "C:/x/y.py"


@pytest.fixture
def local_source_db(tmp_path, monkeypatch):
    db_file = tmp_path / "local_paths.db"
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", str(db_file))
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", str(db_file), raising=False)
    init_db(engine=get_db_engine(db_url, reset=True))

    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO indexed_paths (path, type, recursive, category, repo) VALUES (?, 'directory', 1, 'code', ?)",
            (LOCAL_ROOT, LOCAL_REPO),
        )

        def add_symbol(repo, fp, name, full, kind, start, end):
            return conn.execute(
                "INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'c_sharp')",
                (repo, fp, name, full, kind, start, end, f"{name}()"),
            ).lastrowid

        add_symbol(LOCAL_REPO, _local(CONTROLLER), "ToolsController", "ToolsController", "class_declaration", 1, 60)
        get_id = add_symbol(LOCAL_REPO, _local(CONTROLLER), "GetTool", "ToolsController.GetTool", "method_declaration", 10, 20)
        add_symbol(LOCAL_REPO, _local(SERVICE), "ToolService", "ToolService", "class_declaration", 1, 40)
        add_symbol(LOCAL_REPO, _local(SERVICE), "LoadTool", "ToolService.LoadTool", "method_declaration", 5, 15)
        add_symbol(GIT_REPO, f"{GIT_REPO}://{CLIENT}", "fetchTool", "fetchTool", "function_declaration", 3, 9)

        conn.execute(
            "INSERT INTO ast_relationships (repo, source_symbol_id, source_filepath, source_symbol, target_symbol, relationship_type, line_number) "
            "VALUES (?, ?, ?, 'ToolsController.GetTool', 'ToolService.LoadTool', 'CALLS', 12)",
            (LOCAL_REPO, get_id, _local(CONTROLLER)),
        )
        conn.execute(
            "INSERT INTO api_routes (repo, filepath, framework, http_method, path_pattern, handler_symbol, start_line, end_line) "
            "VALUES (?, ?, 'aspnet', 'GET', '/api/tools/{id}', 'ToolsController.GetTool', 10, 20)",
            (LOCAL_REPO, _local(CONTROLLER)),
        )
        conn.execute(
            "INSERT INTO api_client_calls (repo, filepath, http_method, url_pattern, caller_symbol, line_number) "
            "VALUES (?, ?, 'GET', '/api/tools/{id}', 'fetchTool', 5)",
            (GIT_REPO, f"{GIT_REPO}://{CLIENT}"),
        )
        conn.execute(
            "INSERT INTO api_client_calls (repo, filepath, http_method, url_pattern, caller_symbol, line_number) "
            "VALUES (?, ?, 'GET', '/api/tools/{id}', 'ToolService.LoadTool', 7)",
            (LOCAL_REPO, _local(SERVICE)),
        )


def _run(coro):
    return json.loads(asyncio.run(coro))


def test_find_symbol_returns_relative_paths(local_source_db):
    result = _run(handle_find_symbol(name="GetTool"))
    assert [s["file"] for s in result["symbols"]] == [CONTROLLER]
    git_result = _run(handle_find_symbol(name="fetchTool"))
    assert [s["file"] for s in git_result["symbols"]] == [CLIENT]


def test_get_file_outline_returns_the_relative_path(local_source_db):
    result = _run(handle_get_file_outline(filepath=CONTROLLER, repo=LOCAL_REPO))
    assert result["file"] == CONTROLLER
    assert {s["name"] for s in result["symbols"]} == {"ToolsController", "GetTool"}


def test_find_routes_and_api_callers_return_relative_paths(local_source_db):
    routes = _run(handle_find_routes(query="/api/tools"))
    assert [r["file"] for r in routes["routes"]] == [CONTROLLER]
    callers = _run(handle_find_api_callers(path="/api/tools/{id}"))
    assert sorted(c["file"] for c in callers["callers"]) == sorted([CLIENT, SERVICE])


def test_trace_path_returns_relative_paths(local_source_db):
    result = json.loads(trace_symbol_path("ToolService.LoadTool", repo=LOCAL_REPO, direction="callers"))
    assert result["target"]["file"] == SERVICE
    assert [c["file"] for c in result["callers"]] == [CONTROLLER]
    assert result["callers"][0]["symbol"] == "ToolsController.GetTool"
    handler = json.loads(trace_symbol_path("fetchTool", repo=GIT_REPO, direction="callers"))
    assert handler["target"]["file"] == CLIENT
    assert [h["file"] for call in handler["target"]["http_calls"] for h in call["external_handlers"]] == [CONTROLLER]


def test_diagnose_issue_parts_return_relative_paths(local_source_db):
    routes = match_routes_and_callers([("GET", "/api/tools/42")])
    assert routes[0]["handler"]["file"] == CONTROLLER
    assert sorted(c["file"] for c in routes[0]["external_callers"]) == sorted([CLIENT, SERVICE])

    symbols = match_symbols_and_exceptions([], [], candidate_symbols=["ToolsController.GetTool"])
    assert [s["file"] for s in symbols] == [CONTROLLER]

    with get_db_connection() as conn:
        callers, callees = _get_callers_and_callees(
            conn, LOCAL_REPO, "ToolsController.GetTool", enclosing_filepath=CONTROLLER,
            enclosing_start_line=10, enclosing_end_line=20,
        )
        service_callers, _ = _get_callers_and_callees(conn, LOCAL_REPO, "ToolService.LoadTool")
    assert [c["file"] for c in callees] == [CONTROLLER]
    assert [c["file"] for c in service_callers] == [CONTROLLER]
    assert callers == []


def test_resolved_stack_frames_return_relative_paths(local_source_db):
    frames = [{"path": _local(CONTROLLER), "line": 15, "function": "GetTool"}]
    resolved = resolve_stack_frames(frames, repo=LOCAL_REPO)
    assert resolved[0]["file"] == CONTROLLER
    assert resolved[0]["symbol"] == "ToolsController.GetTool"
    assert [c["file"] for c in resolved[0]["callees"]] == [CONTROLLER]
