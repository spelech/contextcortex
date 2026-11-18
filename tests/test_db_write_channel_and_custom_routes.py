"""Tests for DatabaseWriteChannel bounded queue backpressure, general C# custom route attribute
resolution (IRouteTemplateProvider, IActionHttpMethodProvider, base constructor forwarding),
and TypeScript/JavaScript class field arrow function extraction."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from app.services.chunking.api_route_extractor import (
    extract_api_routes_and_calls,
    match_route_and_call,
)
from app.services.chunking.csharp_route_attributes import (
    evaluate_attribute_usage,
    parse_csharp_attribute_specs,
)
from app.services.chunking.symbol_extractor import extract_symbols_and_chunks
from app.services.database import get_db_connection, init_db
from app.services.indexing.db_write_channel import DatabaseWriteChannel, submit_db_write


def test_database_write_channel_serializes_concurrent_sqlite_writers(tmp_path, monkeypatch):
    """Verifies DatabaseWriteChannel queues concurrent producers through a single writer thread without SQLite lock errors or interleaving."""
    db_file = str(tmp_path / "db_write_channel.db")
    monkeypatch.setenv("CACHE_DB_PATH", db_file)
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", db_file)
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", db_file)
    init_db()

    channel = DatabaseWriteChannel(capacity=4)
    active_writers = 0
    max_concurrent_writers = 0
    guard = threading.Lock()
    writer_thread_ids = set()

    def _make_write_op(idx: int):
        def _op() -> int:
            nonlocal active_writers, max_concurrent_writers
            with guard:
                active_writers += 1
                if active_writers > max_concurrent_writers:
                    max_concurrent_writers = active_writers
                writer_thread_ids.add(threading.get_ident())
            try:
                time.sleep(0.005)
                with get_db_connection() as conn:
                    conn.execute(
                        "INSERT INTO system_metadata (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = EXCLUDED.value",
                        (f"k_{idx}", f"v_{idx}"),
                    )
                    conn.commit()
                return idx
            finally:
                with guard:
                    active_writers -= 1

        return _op

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            futs = [pool.submit(channel.submit, _make_write_op(i)) for i in range(24)]
            results = [f.result(timeout=10.0) for f in futs]

        assert sorted(results) == list(range(24))
        assert max_concurrent_writers == 1
        assert len(writer_thread_ids) == 1

        # Also verify global submit_db_write helper
        val = submit_db_write(lambda: "ok")
        assert val == "ok"
    finally:
        channel.shutdown(wait=True)


def test_general_csharp_custom_route_and_verb_attributes():
    """Verifies custom C# route and HTTP verb attributes are resolved generically from class declarations and inheritance chains."""
    csharp_code = """
using System;
using System.Collections.Generic;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.Routing;

namespace SampleApp.Http
{
    public class VersionedApiControllerAttribute : Attribute, IRouteTemplateProvider
    {
        public const string CONTROLLER_RESOURCE = "[controller]";

        public VersionedApiControllerAttribute(int version, string resource = CONTROLLER_RESOURCE)
        {
            Template = $"api/v{version}/{resource}";
        }

        public string Template { get; }
    }

    public class V3ApiControllerAttribute : VersionedApiControllerAttribute
    {
        public V3ApiControllerAttribute(string resource = "[controller]")
            : base(3, resource)
        {
        }
    }

    public class RestGetByIdAttribute : Attribute, IActionHttpMethodProvider, IRouteTemplateProvider
    {
        public IEnumerable<string> HttpMethods => new[] { "GET" };
        public string Template => "{id:int}";
    }

    public class RestPostByIdAttribute : HttpPostAttribute
    {
    }

    public class RestPutByIdAttribute : HttpPutAttribute
    {
        public RestPutByIdAttribute()
            : base("{id:int?}")
        {
        }
    }

    public class RestDeleteByIdAttribute : HttpDeleteAttribute
    {
        public RestDeleteByIdAttribute()
            : base("{id:int}")
        {
        }
    }

    public abstract class RestController<TResource> : Controller
    {
        [RestGetById]
        public virtual TResource GetResourceById(int id) => default;
    }

    public abstract class ProviderControllerBase<TResource> : RestController<TResource>
    {
        [RestPutById]
        public object UpdateProvider(TResource body) => null;
    }

    [V3ApiController]
    public class MovieController : RestController<object>
    {
        [HttpGet]
        public object AllMovies() => null;

        [RestGetById]
        public object GetById(int id) => null;

        [RestPostById]
        public object AddMovie(object body) => null;

        [RestPutById]
        public object UpdateMovie(object body) => null;

        [RestDeleteById]
        public void DeleteMovie(int id) { }

        [HttpGet("lookup")]
        public object Lookup(string term) => null;
    }

    [V3ApiController("system/status")]
    public class SystemController : Controller
    {
        [HttpGet]
        public object GetStatus() => null;
    }
}
"""
    specs = parse_csharp_attribute_specs(csharp_code)
    assert evaluate_attribute_usage("V3ApiController", None, specs) == (None, "api/v3/[controller]")
    assert evaluate_attribute_usage("V3ApiController", '"system/status"', specs) == (None, "api/v3/system/status")
    assert evaluate_attribute_usage("RestGetById", None, specs) == ("GET", "{id:int}")
    assert evaluate_attribute_usage("RestPostById", None, specs) == ("POST", "")
    assert evaluate_attribute_usage("RestPutById", None, specs) == ("PUT", "{id:int?}")
    assert evaluate_attribute_usage("RestDeleteById", None, specs) == ("DELETE", "{id:int}")

    res = extract_symbols_and_chunks(csharp_code, "src/MovieController.cs", repo="radarr")
    route_set = {(r.http_method, r.path_pattern, r.handler_symbol) for r in res.api_routes}

    assert ("GET", "/api/v3/movie", "MovieController.AllMovies") in route_set
    assert ("GET", "/api/v3/movie/{id}", "MovieController.GetById") in route_set
    assert ("POST", "/api/v3/movie", "MovieController.AddMovie") in route_set
    assert ("PUT", "/api/v3/movie/{id}", "MovieController.UpdateMovie") in route_set
    assert ("DELETE", "/api/v3/movie/{id}", "MovieController.DeleteMovie") in route_set
    assert ("GET", "/api/v3/movie/lookup", "MovieController.Lookup") in route_set
    assert ("GET", "/api/v3/system/status", "SystemController.GetStatus") in route_set
    # Abstract base controllers without a class-level route template should not emit bare "/{id}" routes
    assert all(r.path_pattern != "/{id}" for r in res.api_routes)


def test_typescript_class_field_arrow_methods_and_axios_api_prefix_matching():
    """Verifies TS class field arrow functions are extracted as Class.method symbols and their relative axios calls match /api/v{n} routes."""
    ts_code = """
class RadarrAPI {
  public getMovies = async () => {
    const response = await this.axios.get('/movie');
    return response.data;
  };

  public getMovie = async ({ id }: { id: number }) => {
    const response = await this.axios.get(`/movie/${id}`);
    return response.data;
  };

  public addMovie = async (options: Record<string, unknown>) => {
    const response = await this.axios.post(`/movie`, options);
    return response.data;
  };
}
"""
    res = extract_symbols_and_chunks(ts_code, "server/api/servarr/radarr.ts", repo="overseerr")
    by_full = {s.full_symbol: s for s in res.symbols}

    assert "RadarrAPI" in by_full
    assert "RadarrAPI.getMovies" in by_full
    assert by_full["RadarrAPI.getMovies"].kind == "method_definition"
    assert "RadarrAPI.getMovie" in by_full
    assert "RadarrAPI.addMovie" in by_full

    # Ensure class chunk does not duplicate method bodies
    class_chunks = [c for c in res.chunks if c.symbol == "RadarrAPI"]
    assert all("this.axios.get('/movie')" not in c.content for c in class_chunks)

    call_tuples = [(c.http_method, c.url_pattern, c.caller_symbol) for c in res.api_client_calls]
    assert ("GET", "/movie", "RadarrAPI.getMovies") in call_tuples
    assert ("GET", "/movie/{id}", "RadarrAPI.getMovie") in call_tuples
    assert ("POST", "/movie", "RadarrAPI.addMovie") in call_tuples

    # Relative axios client paths match versioned /api/v3/* server routes
    assert match_route_and_call("/api/v3/movie", "/movie")
    assert match_route_and_call("/api/v3/movie/{id}", "/movie/{id}")
    assert match_route_and_call("/api/v3/movie/lookup", "/movie/lookup")
    assert not match_route_and_call("/api/v3/series", "/movie")


def test_permalinks_are_opt_in_and_direct_tool_aliases_work(tmp_path, monkeypatch):
    """Verifies find_routes and search omit permalinks by default (until include_permalinks=True) and direct tool calls accept common parameter aliases."""
    import asyncio
    import json
    from types import SimpleNamespace
    from unittest.mock import patch

    from app.mcp.handlers.diagnostic_handlers import handle_diagnose_issue
    from app.mcp.handlers.file_handlers import handle_read_file
    from app.mcp.handlers.grep_handlers import handle_grep_code
    from app.mcp.handlers.route_handlers import handle_find_routes
    from app.mcp.handlers.search_handlers import handle_search
    from app.mcp.handlers.symbol_handlers import handle_find_symbol, handle_trace_path

    db_file = str(tmp_path / "opt_in_permalinks.db")
    monkeypatch.setenv("CACHE_DB_PATH", db_file)
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", db_file)
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", db_file)
    init_db()

    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO git_repositories (name, url, branch, commit_sha, provider) VALUES (?, ?, ?, ?, ?)",
            ("radarr", "https://github.com/Radarr/Radarr", "develop", "1234567890abcdef", "github"),
        )
        conn.execute(
            "INSERT INTO api_routes (repo, filepath, framework, http_method, path_pattern, handler_symbol, start_line, end_line) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("radarr", "src/Radarr.Api.V3/Movies/MovieImportController.cs", "aspnet", "POST", "/api/v3/movie/import", "MovieImportController.Import", 18, 25),
        )
        conn.execute(
            "INSERT INTO api_client_calls (repo, filepath, http_method, url_pattern, caller_symbol, line_number) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("radarr", "frontend/src/ImportMovie.ts", "POST", "/api/v3/movie/import", "importMovies", 42),
        )
        conn.execute(
            "INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("radarr", "src/Radarr.Api.V3/Movies/MovieImportController.cs", "Import", "MovieImportController.Import", "method_declaration", 18, 25, "public List<MovieResource> Import()", "c_sharp"),
        )
        conn.commit()

    # 1. find_routes omits permalink by default and accepts `path` / `route` aliases
    routes_default = json.loads(asyncio.run(handle_find_routes(path="/api/v3/movie/import", repo="radarr")))
    assert routes_default["total_routes"] == 1
    assert "permalink" not in routes_default["routes"][0]
    assert "permalink" not in routes_default["callers"][0]

    routes_with_links = json.loads(
        asyncio.run(handle_find_routes(route="/api/v3/movie/import", repo="radarr", include_permalinks=True))
    )
    assert "github.com/Radarr/Radarr/blob/1234567890abcdef" in (routes_with_links["routes"][0].get("permalink") or "")
    assert "github.com/Radarr/Radarr/blob/1234567890abcdef" in (routes_with_links["callers"][0].get("permalink") or "")

    # 2. search omits permalink by default and includes it when include_permalinks=True
    fake_hit = SimpleNamespace(
        payload={
            "repo": "radarr",
            "rel_path": "src/Radarr.Api.V3/Movies/MovieImportController.cs",
            "start_line": 18,
            "end_line": 25,
            "full_symbol": "MovieImportController.Import",
            "kind": "method_declaration",
            "language": "c_sharp",
            "permalink_url": "https://github.com/Radarr/Radarr/blob/1234567890abcdef/src/MovieImportController.cs#L18-L25",
            "content": "public List<MovieResource> Import()",
        },
        score=0.95,
        dense_score=0.9,
        sparse_score=0.8,
    )
    with patch("app.mcp.tools.execute_hybrid_search", return_value=[fake_hit]):
        search_default = json.loads(asyncio.run(handle_search(query="Import", repo="radarr")))
        assert "permalink" not in search_default["results"][0]
        search_with_link = json.loads(
            asyncio.run(handle_search(query="Import", repo="radarr", include_permalinks=True))
        )
        assert search_with_link["results"][0]["permalink"].startswith("https://github.com/Radarr/Radarr/blob/")

    # 3. find_symbol accepts `query` alias, trace_path accepts `name`/`query`, read_file accepts `filepath`,
    #    grep_code accepts `query`/`filepath`, and diagnose_issue accepts `query`/`error`.
    sym_res = json.loads(asyncio.run(handle_find_symbol(query="MovieImportController.Import", repo="radarr")))
    assert sym_res["total"] == 1 and sym_res["symbols"][0]["symbol"] == "MovieImportController.Import"

    with patch("app.mcp.tools.trace_symbol_path", return_value={"target": {"symbol": "MovieImportController.Import"}, "callers": [], "callees": []}):
        trace_res = json.loads(asyncio.run(handle_trace_path(name="MovieImportController.Import", repo="radarr")))
        assert trace_res["target"]["symbol"] == "MovieImportController.Import"

    outline_res = json.loads(
        asyncio.run(
            handle_read_file(
                filepath="src/Radarr.Api.V3/Movies/MovieImportController.cs",
                repo="radarr",
                outline_only=True,
            )
        )
    )
    assert outline_res["total_symbols"] == 1

    with patch("app.mcp.handlers.diagnostic_handlers.diagnose_issue", return_value={"call_chain": {"entry": "Import", "terms": [], "steps": [], "other_hits": [], "nodes_read": 1}}):
        diag_res = json.loads(asyncio.run(handle_diagnose_issue(error="NullReferenceException in Import", repo="radarr")))
        assert diag_res["call_chain"]["entry"] == "Import"

    fake_reader = SimpleNamespace(
        storage_root=str(tmp_path),
        grep_code=lambda **kw: {
            "matches": [
                {
                    "repo": "radarr",
                    "file": kw.get("path_glob") or "MovieImportController.cs",
                    "line": 18,
                    "match_text": kw.get("pattern"),
                    "context": [],
                    "permalink": "https://github.com/Radarr/Radarr/blob/123/MovieImportController.cs#L18",
                }
            ]
        },
    )
    with patch("app.mcp.handlers.grep_handlers._resolve_reader_factory", return_value=lambda: fake_reader):
        grep_res = json.loads(asyncio.run(handle_grep_code(query="Import", filepath="MovieImportController.cs")))
        assert grep_res["total_matches"] == 1
        assert grep_res["path_filter"] == "MovieImportController.cs"
        assert "permalink" not in grep_res["files"][0]


def test_code_mode_disabled_omits_execute_script_and_sse_post_routes_to_mcp(monkeypatch):
    """Verifies CODE_MODE_ENABLED=false omits execute_script from get_tool_definitions() and McpPingMiddleware routes POST /sse to /mcp."""
    import asyncio
    from app.mcp.mcp_server import build_mcp_server_instructions
    from app.mcp.tools import get_tool_definitions
    from main import McpPingMiddleware

    monkeypatch.setenv("CODE_MODE_ENABLED", "false")
    names_disabled = {name for name, _fn, _desc in get_tool_definitions()}
    assert "execute_script" not in names_disabled
    assert "execute_script" not in build_mcp_server_instructions()

    monkeypatch.setenv("CODE_MODE_ENABLED", "true")
    names_enabled = {name for name, _fn, _desc in get_tool_definitions()}
    assert "execute_script" in names_enabled
    assert "execute_script" in build_mcp_server_instructions()

    captured_scopes = []

    async def _dummy_app(scope, receive, send):
        captured_scopes.append(dict(scope))

    mw = McpPingMiddleware(_dummy_app)

    async def _empty_receive():
        return {"type": "http.request", "body": b"{}", "more_body": False}

    async def _noop_send(_msg):
        pass

    # POST /sse without session_id routes to /mcp for Streamable HTTP clients
    asyncio.run(
        mw(
            {"type": "http", "method": "POST", "path": "/sse", "query_string": b""},
            _empty_receive,
            _noop_send,
        )
    )
    assert captured_scopes[-1]["path"] == "/mcp"

    # GET /sse stays on /sse for legacy SSE transport
    asyncio.run(
        mw(
            {"type": "http", "method": "GET", "path": "/sse", "query_string": b""},
            _empty_receive,
            _noop_send,
        )
    )
    assert captured_scopes[-1]["path"] == "/sse"

