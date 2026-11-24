"""Regression tests for Issue #219: plain-language bug report expansion into code-concept queries, RRF fusion, and area diversification."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.mcp.handlers.search_handlers import handle_search
from app.services.database import get_db_connection
from app.services.database.engine import get_db_engine, init_db
from app.services.diagnostics import diagnose_issue
from app.services.expanded_search import area_key_for_path, extract_evidence_line, run_expanded_code_search
from app.services.query_expansion import clear_expansion_cache, expand_report_to_code_queries
from app.services.vector_store.base import VectorSearchResult


@pytest.fixture
def repo_db(tmp_path, monkeypatch):
    clear_expansion_cache()
    db_file = tmp_path / "issue_219.db"
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.delenv("CHAT_MODEL", raising=False)
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", str(db_file))
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", str(db_file), raising=False)
    init_db(engine=get_db_engine(db_url, reset=True))
    with get_db_connection() as conn:
        syms = [
            ("shop", "shop://Services/RelatedItems/RelatedItemsBuilder.cs", "Build", "RelatedItemsBuilder.Build", "method", 72, 148, "c_sharp"),
            ("shop", "shop://Services/RelatedItems/RelatedItemsBuilder.cs", "FilterInlineAccessories", "RelatedItemsBuilder.FilterInlineAccessories", "method", 150, 190, "c_sharp"),
            ("shop", "shop://Services/RelatedItems/RelatedItemsRetriever.cs", "GetRelatedProducts", "RelatedItemsRetriever.GetRelatedProducts", "method", 20, 65, "c_sharp"),
            ("shop", "shop://Services/Catalog/ProductCatalogService.cs", "ShowInlineProduct", "ProductCatalogService.ShowInlineProduct", "method", 10, 50, "c_sharp"),
            ("shop", "shop://Services/Filters/SpecFilterService.cs", "ApplySpecFilter", "SpecFilterService.ApplySpecFilter", "method", 15, 60, "c_sharp"),
            ("shop", "shop://Tests/TestData/RpgFixtureTests.cs", "RpgSpecTest", "RpgFixtureTests.RpgSpecTest", "method", 1, 20, "c_sharp"),
        ]
        conn.executemany(
            "INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            syms,
        )
        files = [
            ("shop://Services/RelatedItems/RelatedItemsBuilder.cs", "shop", "code", "c_sharp"),
            ("shop://Services/RelatedItems/RelatedItemsRetriever.cs", "shop", "code", "c_sharp"),
            ("shop://Services/Catalog/ProductCatalogService.cs", "shop", "code", "c_sharp"),
            ("shop://Services/Filters/SpecFilterService.cs", "shop", "code", "c_sharp"),
            ("shop://TestData/Rpg/sample1.html", "shop", "doc", "html"),
            ("shop://TestData/Rpg/sample2.html", "shop", "doc", "html"),
            ("shop://docs/rpg_spec_guide.md", "shop", "doc", "markdown"),
        ]
        conn.executemany(
            "INSERT INTO indexed_files (filepath, repo, doc_type, language) VALUES (?, ?, ?, ?)",
            files,
        )
        conn.commit()
    yield tmp_path
    clear_expansion_cache()


def _hit(hit_id: str, path: str, symbol: str, score: float, content: str, start: int = 10, end: int = 40) -> VectorSearchResult:
    return VectorSearchResult(
        id=hit_id,
        score=score,
        dense_score=score,
        sparse_score=score * 0.5,
        payload={
            "repo": "shop",
            "doc_type": "code",
            "language": "c_sharp",
            "rel_path": path,
            "symbol": symbol,
            "full_symbol": symbol,
            "start_line": start,
            "end_line": end,
            "content": content,
        },
    )


def test_219_llm_report_expansion_caches_by_hash_and_falls_back_on_error(repo_db, monkeypatch):
    monkeypatch.setenv("CHAT_MODEL", "gpt-4o-mini")
    fake_resp = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=(
                        "```json\n"
                        '["related products shown inline for primary product", '
                        '"root master part number of related product", '
                        '"reverse lookup primary products by related item", '
                        '"component hidden when master is also related"]\n'
                        "```"
                    )
                )
            )
        ]
    )
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = fake_resp

    report = "Accessory SKU-4410 does not show inline for SuperWidget 9000, but shows when filtered by spec RPG."
    with patch("app.services.query_expansion._build_llm_client", return_value=fake_client):
        q1, src1 = expand_report_to_code_queries(report, repo="shop")
        # Same report with extra whitespace must hit the SHA-256 hash cache without a second LLM call.
        q2, src2 = expand_report_to_code_queries("  " + report.replace(" ", "  ") + "\n", repo="shop")

    assert src1 == "llm" and src2 == "llm"
    assert q1 == q2 and len(q1) == 4
    assert fake_client.chat.completions.create.call_count == 1

    # On LLM error, gracefully fall back to the heuristic splitter.
    clear_expansion_cache()
    failing_client = MagicMock()
    failing_client.chat.completions.create.side_effect = RuntimeError("gateway offline")
    with patch("app.services.query_expansion._build_llm_client", return_value=failing_client):
        q3, src3 = expand_report_to_code_queries(report, repo="shop")
    assert src3 == "heuristic" and len(q3) >= 2


def test_219_heuristic_splits_clauses_and_prunes_low_df_and_test_only_tokens(repo_db):
    report = (
        "An accessory (SKU-4410) does not show inline for product SuperWidget 9000 on the catalog page, "
        "but shows when the page is filtered by spec value RPG Stainless316."
    )
    queries, source = expand_report_to_code_queries(report, repo="shop")

    assert source == "heuristic"
    assert 3 <= len(queries) <= 6
    joined = " ".join(queries).lower()
    # Data values, brand/product names, and test/doc-only tokens must be removed.
    for noise in ("sku-4410", "superwidget", "9000", "stainless316", "rpg"):
        assert noise not in joined
    # Symbol-backed code concepts must be preserved.
    for concept in ("accessory", "inline", "product", "catalog", "filter", "spec"):
        assert concept in joined
    # First clause isolates the inline accessory symptom without filter/spec terms.
    assert "accessory" in queries[0] and "inline" in queries[0]
    assert "filter" not in queries[0] and "spec" not in queries[0]


def test_219_rrf_fusion_diversifies_files_and_folders_with_evidence(repo_db):
    builder_code = (
        "using System;\n"
        "public class RelatedItemsBuilder\n"
        "{\n"
        "    public void Build()\n"
        "    {\n"
        "        if (master == related || !lookup.ContainsKey(master))\n"
        "            items.Remove(component);\n"
        "    }\n"
        "}"
    )
    retriever_code = "public List<Item> GetRelatedProducts() { return lookup.Where(x => x.IsInline).ToList(); }"
    catalog_code = "public View RenderInline() { return catalog.ShowInline(product); }"

    # Sub-queries return many hits from Filters/ plus cross-query hits in RelatedItems/ and Catalog/.
    def _fake_search(query_text: str, **_kw):
        q_low = query_text.lower()
        if "filter" in q_low and "inline" not in q_low:
            return [
                _hit("f1", "Services/Filters/FilterA.cs", "FilterA.Run", 0.90, "return query.Where(f => f.Active);"),
                _hit("f2", "Services/Filters/FilterA.cs", "FilterA.Apply", 0.88, "return applyFilter(spec);", 50, 80),
                _hit("f3", "Services/Filters/FilterA.cs", "FilterA.Reset", 0.86, "reset();", 90, 110),
                _hit("f4", "Services/Filters/FilterB.cs", "FilterB.Run", 0.85, "return filterB(spec);"),
                _hit("f5", "Services/Filters/FilterC.cs", "FilterC.Run", 0.84, "return filterC(spec);"),
                _hit("rb1", "Services/RelatedItems/RelatedItemsBuilder.cs", "RelatedItemsBuilder.Build", 0.72, builder_code, 72, 148),
            ]
        return [
            _hit("rb1", "Services/RelatedItems/RelatedItemsBuilder.cs", "RelatedItemsBuilder.Build", 0.91, builder_code, 72, 148),
            _hit("rr1", "Services/RelatedItems/RelatedItemsRetriever.cs", "RelatedItemsRetriever.GetRelatedProducts", 0.82, retriever_code, 20, 65),
            _hit("cat1", "Services/Catalog/ProductCatalogService.cs", "ProductCatalogService.ShowInlineProduct", 0.75, catalog_code, 10, 50),
            _hit("inv1", "Services/Inventory/StockService.cs", "StockService.IsAvailable", 0.71, "return stock.Count > 0;"),
            _hit("f1", "Services/Filters/FilterA.cs", "FilterA.Run", 0.70, "return query.Where(f => f.Active);"),
        ]

    report = (
        "An accessory does not show inline for a related product on the catalog page, "
        "but shows when filtered by spec."
    )
    outcome = run_expanded_code_search(report, search_fn=_fake_search, repo="shop", limit=6, max_per_file=2, max_per_area=2)

    assert len(outcome.queries) >= 3
    assert outcome.areas[0]["file"] == "Services/RelatedItems/RelatedItemsBuilder.cs"
    assert outcome.areas[0]["symbol"] == "RelatedItemsBuilder.Build"
    assert outcome.areas[0]["lines"] == [72, 148]
    assert len(outcome.areas[0]["matched_by"]) >= 2
    assert "if (master == related || !lookup.ContainsKey(master))" in outcome.areas[0]["evidence"]

    # Diversification: Filters folder must not crowd out RelatedItems or Catalog, and no file > 2 hits.
    area_folders = {a["area"] for a in outcome.areas}
    assert {"Services/RelatedItems", "Services/Catalog", "Services/Filters"}.issubset(area_folders)
    filter_counts = sum(1 for h in outcome.hits if area_key_for_path(h.payload["rel_path"]) == "Services/Filters")
    assert filter_counts <= 2
    assert extract_evidence_line("using System;\n{\n    if (x == y) return false;\n}", ["check x"]) == "if (x == y) return false;"


def test_219_diagnose_issue_expands_plain_language_and_skips_when_resolved(repo_db):
    builder_hit = _hit(
        "rb1",
        "Services/RelatedItems/RelatedItemsBuilder.cs",
        "RelatedItemsBuilder.Build",
        0.78,
        "public void Build() {\n    if (master == related) items.Remove(component);\n}",
        72,
        148,
    )
    plain_report = (
        "An accessory does not show inline for a product on the catalog page, "
        "but shows when filtered by a spec value."
    )
    with patch("app.services.diagnostics.execute_hybrid_search", return_value=[builder_hit]) as mock_search:
        plain_res = diagnose_issue(plain_report, repo="shop", limit=5)

    assert mock_search.call_count == len(plain_res["queries"]) >= 3
    assert plain_res["areas"][0]["file"] == "Services/RelatedItems/RelatedItemsBuilder.cs"
    assert plain_res["areas"][0]["symbol"] == "RelatedItemsBuilder.Build"
    assert "if (master == related)" in plain_res["areas"][0]["evidence"]
    assert plain_res["semantic_candidates"][0]["file"] == "Services/RelatedItems/RelatedItemsBuilder.cs"

    # When concrete code symbols resolve, diagnose_issue keeps standard non-expanded behavior.
    resolved_report = "RelatedItemsBuilder.Build throws InvalidOperationException on empty lookup"
    with patch("app.services.diagnostics.execute_hybrid_search", return_value=[builder_hit]) as mock_search2:
        resolved_res = diagnose_issue(resolved_report, repo="shop", limit=5)
    assert mock_search2.call_count == 1
    assert "queries" not in resolved_res and "areas" not in resolved_res


def test_219_mcp_search_expand_flag_returns_queries_and_areas(repo_db):
    builder_hit = _hit(
        "rb1",
        "Services/RelatedItems/RelatedItemsBuilder.cs",
        "RelatedItemsBuilder.Build",
        0.81,
        "if (master == related || !lookup.ContainsKey(master)) items.Remove(component);",
        72,
        148,
    )
    report = "Accessory does not show inline for product on catalog page, but shows when filtered by spec."
    with patch("app.mcp.tools.execute_hybrid_search", return_value=[builder_hit]) as mock_search:
        expanded_payload = json.loads(asyncio.run(handle_search(query=report, scope="code", repo="shop", expand=True)))
        normal_payload = json.loads(asyncio.run(handle_search(query=report, scope="code", repo="shop", expand=False)))

    assert len(expanded_payload["queries"]) >= 3
    assert expanded_payload["areas"][0]["file"] == "Services/RelatedItems/RelatedItemsBuilder.cs"
    assert expanded_payload["areas"][0]["matched_by"] == list(range(len(expanded_payload["queries"])))
    assert "if (master == related" in expanded_payload["areas"][0]["evidence"]
    assert expanded_payload["results"][0]["file"] == "Services/RelatedItems/RelatedItemsBuilder.cs"

    assert "queries" not in normal_payload and "areas" not in normal_payload
    assert mock_search.call_count == len(expanded_payload["queries"]) + 1
