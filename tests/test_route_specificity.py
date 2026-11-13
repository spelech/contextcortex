"""find_api_callers and trace_path: a client call belongs only to the most specific route that matches it."""

import json

import pytest

from app.mcp.tools import handle_find_routes
from app.services.chunking.api_route_extractor import match_route_and_call
from app.services.chunking.route_specificity import (
    call_belongs_to_route,
    compare_specificity,
    most_specific_routes,
)
from app.services.database import get_db_connection, init_db
from app.services.search import trace_symbol_path

ID_ROUTE = "api/v{version}/assistants/{id}"
DETAILS_ROUTE = "api/v{version}/assistants/details"
DRAFTS_ROUTE = "api/v{version}/assistants/drafts"
BUNDLES_ROUTE = "api/v{version}/assistants/system-tool-bundles"


def _route(path, method="GET", repo="hub-api"):
    return {"repo": repo, "http_method": method, "path_pattern": path}


HUB_ROUTES = [_route(ID_ROUTE), _route(DETAILS_ROUTE), _route(DRAFTS_ROUTE), _route(BUNDLES_ROUTE)]


def _paths(routes):
    return sorted(r["path_pattern"] for r in routes)


def test_literal_segment_beats_parameter():
    assert compare_specificity(DETAILS_ROUTE, ID_ROUTE) == 1
    assert compare_specificity(ID_ROUTE, DETAILS_ROUTE) == -1
    assert compare_specificity(DETAILS_ROUTE, DRAFTS_ROUTE) == 0
    # Segment by segment from the left: the first literal-versus-parameter segment decides.
    assert compare_specificity("/a/{x}/c", "/{y}/b/c") == 1
    # A mixed segment (v{version}) beats a parameter but loses to a literal.
    assert compare_specificity("/api/v{version}/x", "/api/{v}/x") == 1
    assert compare_specificity("/api/v2/x", "/api/v{version}/x") == 1


def test_match_route_and_call_still_matches_the_general_route():
    # The plain matcher is unchanged: the specificity rule is applied by its callers.
    assert match_route_and_call(ID_ROUTE, "/api/v2/Assistants/details")


@pytest.mark.parametrize("url, expected", [
    ("/api/v2/Assistants/details", [DETAILS_ROUTE]),
    ("/api/v2/Assistants/drafts", [DRAFTS_ROUTE]),
    ("/api/v2/Assistants/system-tool-bundles", [BUNDLES_ROUTE]),
    ("/api/v2/Assistants/{instanceId}", [ID_ROUTE]),
    ("/api/v2/Assistants/3f2c9a", [ID_ROUTE]),
    ("/{baseUrl}/api/v2/Assistants/details", [DETAILS_ROUTE]),
    ("/{baseUrl}/api/v2/Assistants/{id}", [ID_ROUTE]),
    ("https://hub.example.com/api/v2/Assistants/drafts?latestOnly=true", [DRAFTS_ROUTE]),
])
def test_call_goes_to_most_specific_route(url, expected):
    assert _paths(most_specific_routes(url, "GET", HUB_ROUTES)) == expected


def test_method_and_repository_are_resolved_separately():
    routes = [_route(ID_ROUTE), _route(DETAILS_ROUTE, method="POST"), _route(DETAILS_ROUTE, repo="other-api")]
    # The POST details route does not compete for a GET call.
    assert call_belongs_to_route(routes[0], "/api/v2/Assistants/details", "GET", routes)
    # A route of another repository does not take the call away from hub-api's route.
    owners = most_specific_routes("/api/v2/Assistants/details", "GET", routes)
    assert sorted((r["repo"], r["path_pattern"]) for r in owners) == [("hub-api", ID_ROUTE), ("other-api", DETAILS_ROUTE)]
    assert not call_belongs_to_route(_route(ID_ROUTE), "/api/v2/Assistants/details", "GET", HUB_ROUTES)


ROUTE_ROWS = [
    ("hub-api", "Controllers/AssistantsController.cs", "GET", ID_ROUTE, "AssistantsController.GetById", 20),
    ("hub-api", "Controllers/AssistantsController.cs", "GET", DETAILS_ROUTE, "AssistantsController.GetDetails", 40),
    ("hub-api", "Controllers/AssistantsController.cs", "GET", DRAFTS_ROUTE, "AssistantsController.GetDrafts", 60),
    ("hub-api", "Controllers/AssistantsController.cs", "GET", BUNDLES_ROUTE, "AssistantsController.GetBundles", 80),
    ("hub-api", "Tests/FakeAssistantsController.cs", "GET", "api/v2/assistants/{id}", "FakeAssistantsController.Get", 10),
]

CALL_ROWS = [
    ("hub-ui", "src/api.ts", "GET", "/api/v2/Assistants/details", "getDetails", 10),
    ("hub-ui", "src/api.ts", "GET", "/api/v2/Assistants/drafts", "getDrafts", 20),
    ("hub-ui", "src/api.ts", "GET", "/api/v2/Assistants/system-tool-bundles", "getBundles", 30),
    ("hub-ui", "src/api.ts", "GET", "/api/v2/Assistants/{instanceId}", "getAssistant", 40),
    ("hub-sdk", "Client.cs", "GET", "/{baseUrl}/api/v2/Assistants/details", "AssistantsClient.GetDetails", 50),
    ("hub-sdk", "Client.cs", "GET", "/{baseUrl}/api/v2/Assistants/{id}", "AssistantsClient.Get", 60),
    ("hub-ui", "src/legacy.ts", "GET", "/legacy/items/details", "getLegacyDetails", 70),
]


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    monkeypatch.setenv("CACHE_DB_PATH", str(tmp_path / "route_specificity.db"))
    init_db()
    with get_db_connection() as conn:
        for repo, path, method, pattern, handler, line in ROUTE_ROWS:
            conn.execute(
                "INSERT INTO api_routes (repo, filepath, framework, http_method, path_pattern, handler_symbol, start_line, end_line) VALUES (?, ?, 'aspnet', ?, ?, ?, ?, ?)",
                (repo, path, method, pattern, handler, line, line + 10),
            )
            conn.execute(
                "INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language) VALUES (?, ?, ?, ?, 'method', ?, ?, '', 'csharp')",
                (repo, path, handler.rsplit(".", 1)[-1], handler, line, line + 10),
            )
        for repo, path, method, url, caller, line in CALL_ROWS:
            conn.execute(
                "INSERT INTO api_client_calls (repo, filepath, http_method, url_pattern, caller_symbol, line_number) VALUES (?, ?, ?, ?, ?, ?)",
                (repo, path, method, url, caller, line),
            )
            conn.execute(
                "INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language) VALUES (?, ?, ?, ?, 'function', ?, ?, '', 'typescript')",
                (repo, path, caller.rsplit(".", 1)[-1], caller, line - 2, line + 2),
            )
        conn.commit()


async def _callers(path, method=None):
    out = json.loads(await handle_find_routes(query=path, kind="callers", method=method))
    return sorted(c["caller"] for c in out["callers"])


@pytest.mark.asyncio
async def test_find_api_callers_general_route_skips_calls_of_specific_routes(seeded_db):
    expected = ["AssistantsClient.Get", "getAssistant"]
    assert await _callers(ID_ROUTE) == expected
    assert await _callers(ID_ROUTE, method="GET") == expected
    # A concrete version in the target path resolves to the same route.
    assert await _callers("/api/v2/assistants/{id}") == expected


@pytest.mark.asyncio
async def test_find_api_callers_specific_route_keeps_its_calls(seeded_db):
    assert await _callers(DETAILS_ROUTE) == ["AssistantsClient.GetDetails", "getDetails"]
    assert await _callers(DRAFTS_ROUTE) == ["getDrafts"]
    assert await _callers(BUNDLES_ROUTE) == ["getBundles"]


@pytest.mark.asyncio
async def test_find_api_callers_without_known_route_keeps_every_match(seeded_db):
    # No indexed route matches the target, so there is nothing more specific to compare with.
    assert await _callers("/legacy/items/{id}") == ["getLegacyDetails"]


def test_trace_path_external_callers_and_handlers_use_most_specific_route(seeded_db):
    # The more specific route in Tests/ (api/v2/...) does not take the {id} calls away from the real route.
    by_id = json.loads(trace_symbol_path("AssistantsController.GetById", repo="hub-api", direction="callers", depth=1))
    callers = sorted(c["symbol"] for c in by_id["target"]["external_callers"])
    assert callers == ["AssistantsClient.Get", "getAssistant"]

    details_call = json.loads(trace_symbol_path("getDetails", repo="hub-ui", direction="callees", depth=1))
    handlers = {h["symbol"] for h in details_call["target"]["http_calls"][0]["external_handlers"]}
    assert "AssistantsController.GetDetails" in handlers
    assert "AssistantsController.GetById" not in handlers
