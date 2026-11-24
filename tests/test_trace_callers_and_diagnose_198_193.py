"""Regression tests for Issue #198 (trace_path caller ranking & BFS budgets) and reopened Issue #193."""

import json
from unittest.mock import patch

import pytest

from app.services.database import get_db_connection
from app.services.database.engine import get_db_engine, init_db
from app.services.diagnostic_error_terms import extract_error_terms
from app.services.diagnostic_route_path import clean_plain_language_query
from app.services.diagnostics import diagnose_issue
from app.services.graph_traversal import trace_symbol_path
from app.services.vector_store.base import VectorSearchResult

REPO = "shop"


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    db_file = tmp_path / "trace_diag_198_193.db"
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", str(db_file))
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", str(db_file), raising=False)
    init_db(engine=get_db_engine(db_url, reset=True))


def _seed_build_graph():
    with get_db_connection() as conn:
        def add_sym(fp, name, full, kind, start, end, sig):
            return conn.execute(
                "INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'c_sharp')",
                (REPO, f"{REPO}://{fp}", name, full, kind, start, end, sig),
            ).lastrowid

        # Three unrelated classes all defining `Build()`
        add_sym("Factories/ProductFactory.cs", "ProductFactory", "ProductFactory", "class_declaration", 1, 50, "public class ProductFactory : IProductFactory")
        add_sym("Factories/ProductFactory.cs", "Build", "ProductFactory.Build", "method_declaration", 10, 30, "public Product Build()")
        add_sym("Factories/IProductFactory.cs", "IProductFactory", "IProductFactory", "interface_declaration", 1, 10, "public interface IProductFactory")
        add_sym("Factories/IProductFactory.cs", "Build", "IProductFactory.Build", "method_declaration", 3, 3, "Product Build()")
        conn.execute(
            "INSERT INTO ast_relationships (repo, source_filepath, source_symbol, target_symbol, relationship_type, line_number) "
            "VALUES (?, 'shop://Factories/ProductFactory.cs', 'ProductFactory', 'IProductFactory', 'IMPLEMENTS', 1)",
            (REPO,),
        )

        add_sym("Nav/BreadcrumbNamer.cs", "BreadcrumbNamer", "BreadcrumbNamer", "class_declaration", 1, 40, "public class BreadcrumbNamer")
        add_sym("Nav/BreadcrumbNamer.cs", "Build", "BreadcrumbNamer.Build", "method_declaration", 10, 20, "public string Build()")
        add_sym("Data/SqlAdapter.cs", "SqlAdapter", "SqlAdapter", "class_declaration", 1, 40, "public class SqlAdapter")
        add_sym("Data/SqlAdapter.cs", "Build", "SqlAdapter.Build", "method_declaration", 10, 20, "public SqlQuery Build()")

        # Real caller holding IProductFactory (appears at a LATER line number than noise callers)
        add_sym("Web/CatalogPresenter.cs", "CatalogPresenter", "CatalogPresenter", "class_declaration", 1, 100, "public class CatalogPresenter")
        add_sym("Web/CatalogPresenter.cs", "CatalogPresenter", "CatalogPresenter.CatalogPresenter", "constructor_declaration", 5, 8, "public CatalogPresenter(IProductFactory factory)")
        pres_id = add_sym("Web/CatalogPresenter.cs", "Render", "CatalogPresenter.Render", "method_declaration", 50, 90, "public View Render()")

        # Unrelated noise callers calling bare `Build` at EARLIER line numbers
        add_sym("Web/BreadcrumbController.cs", "BreadcrumbController", "BreadcrumbController", "class_declaration", 1, 50, "public class BreadcrumbController")
        bc_id = add_sym("Web/BreadcrumbController.cs", "Show", "BreadcrumbController.Show", "method_declaration", 10, 30, "public void Show()")
        add_sym("Web/Router.cs", "Router", "Router", "class_declaration", 1, 40, "public class Router")
        router_id = add_sym("Web/Router.cs", "Dispatch", "Router.Dispatch", "method_declaration", 5, 25, "public void Dispatch()")

        # Noise caller has an earlier line_number (12) than real caller (75)
        conn.execute(
            "INSERT INTO ast_relationships (repo, source_symbol_id, source_filepath, source_symbol, target_symbol, relationship_type, line_number) VALUES (?, ?, 'shop://Web/BreadcrumbController.cs', 'Show', 'Build', 'CALLS', 12)",
            (REPO, bc_id),
        )
        conn.execute(
            "INSERT INTO ast_relationships (repo, source_symbol_id, source_filepath, source_symbol, target_symbol, relationship_type, line_number) VALUES (?, ?, 'shop://Web/CatalogPresenter.cs', 'Render', 'Build', 'CALLS', 75)",
            (REPO, pres_id),
        )
        # Depth-2 caller of the noise caller (must NOT be expanded when BreadcrumbController.Show is name_only)
        conn.execute(
            "INSERT INTO ast_relationships (repo, source_symbol_id, source_filepath, source_symbol, target_symbol, relationship_type, line_number) VALUES (?, ?, 'shop://Web/Router.cs', 'Dispatch', 'BreadcrumbController.Show', 'CALLS', 10)",
            (REPO, router_id),
        )
        conn.commit()


def test_198_resolved_callers_rank_above_name_only_and_name_only_not_expanded(isolated_db):
    _seed_build_graph()
    res = json.loads(trace_symbol_path("ProductFactory.Build", repo=REPO, direction="callers", depth=3, limit=50))
    callers = res["callers"]
    assert len(callers) == 2
    assert callers[0]["symbol"] == "CatalogPresenter.Render"
    assert "confidence" not in callers[0]
    assert callers[1]["symbol"] == "BreadcrumbController.Show"
    assert callers[1]["confidence"] == "name_only"
    # name_only caller must not fan out to Router.Dispatch at depth 2
    assert callers[1]["callers"] == []


def test_198_time_budget_stops_traversal_and_sets_truncation_reason(isolated_db):
    _seed_build_graph()
    ticks = iter([0.0, 0.0, 20.0, 20.0])
    with patch("app.services.graph_traversal.time.monotonic", side_effect=lambda: next(ticks, 20.0)):
        res = json.loads(
            trace_symbol_path("ProductFactory.Build", repo=REPO, direction="callers", depth=3, limit=50, max_seconds=1.0)
        )
    assert res["truncated"] is True
    assert res.get("truncation_reason", "").startswith("time_budget_exceeded")


def test_193_filler_words_excluded_from_error_terms_and_plain_query():
    report = (
        "## Bug report\n"
        "Customer already checked back and is doing drill down on product 1234-ABCD (SKU-98765): "
        "the accessory is missing from the listing unless a spec filter is applied."
    )
    terms = extract_error_terms(report)
    for filler in ("already", "back", "checked", "doing", "down", "customer", "1234-abcd", "sku-98765"):
        assert filler not in terms
    assert "accessory" in terms
    assert "listing" in terms
    assert "filter" in terms

    cleaned = clean_plain_language_query(report)
    assert "1234-ABCD" not in cleaned
    assert "SKU-98765" not in cleaned
    assert "already" not in cleaned.lower().split()
    assert "accessory" in cleaned.lower()
    assert "filter" in cleaned.lower()


def test_193_plain_language_low_score_candidates_dropped_with_search_hint(isolated_db):
    report = "Accessory does not show on the listing page unless a spec filter is applied."
    low_noise = [
        VectorSearchResult(
            id="noise-1",
            score=0.03,
            dense_score=0.03,
            payload={
                "repo": REPO,
                "doc_type": "code",
                "rel_path": "Utils/IdIndex.cs",
                "symbol": "IdIndex.Lookup",
                "language": "c_sharp",
                "start_line": 1,
                "end_line": 10,
                "content": "public int Lookup() => 0;",
            },
        ),
    ]
    with patch("app.services.diagnostics.execute_hybrid_search", return_value=low_noise):
        res = diagnose_issue(report, repo=REPO, limit=5)

    assert res["semantic_candidates"] == []
    assert "hint" in res and "search(" in res["hint"]


def test_193_server_instructions_and_tool_guidance_route_plain_descriptions_to_search():
    from mcp.server.fastmcp import FastMCP
    from app.mcp.mcp_server import build_mcp_server_instructions
    from app.mcp.tools import register_mcp_tools_and_resources

    instructions = build_mcp_server_instructions()
    assert "plain-language" in instructions.lower()
    assert "start with search" in instructions.lower()

    server = register_mcp_tools_and_resources(FastMCP("GuidanceCheck"))
    tools = {t.name: t for t in server._tool_manager.list_tools()}
    assert "start with search" in tools["diagnose_issue"].description.lower()
    assert "start with search" in tools["execute_script"].description.lower()
