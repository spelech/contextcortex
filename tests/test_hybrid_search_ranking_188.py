"""Regression tests for Issue #188: hybrid fusion and diagnose_issue ranking on large repos."""

from unittest.mock import MagicMock, patch

import pytest

from app.services.database import get_db_connection
from app.services.database.engine import get_db_engine, init_db
from app.services.diagnostic_route_path import keep_semantic_hit
from app.services.diagnostics import diagnose_issue
from app.services.query_router import (
    classify_query_intent,
    fuse_search_results,
    should_early_return_lexical,
)
from app.services.search import execute_hybrid_search
from app.services.vector_store.base import VectorSearchResult
from app.services.vector_store.pgvector_store import PgVectorStore
from app.services.vector_store.qdrant_queries import execute_qdrant_search


def _mock_qdrant_point(pid: str, score: float, payload: dict):
    pt = MagicMock()
    pt.id = pid
    pt.score = score
    pt.payload = payload
    return pt


def test_pgvector_hybrid_ranks_semantic_code_above_lexical_only_fixture_and_css():
    """Dense-only relevant code must outrank weak lexical-only hits, fixture summaries, CSS, and minified files."""
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    dense_result = MagicMock()
    dense_result.mappings.return_value.fetchall.return_value = [
        {
            "id": "cs-dual",
            "score": 0.53,
            "payload": {
                "repo": "shop",
                "doc_type": "code",
                "rel_path": "Services/CatalogFilter.cs",
                "symbol": "CatalogFilter.ApplyVisibilityRules",
                "language": "c_sharp",
                "content": "public IQueryable<Product> ApplyVisibilityRules(IQueryable<Product> q) => q;",
            },
        },
        {
            "id": "cs-dense-only",
            "score": 0.58,
            "payload": {
                "repo": "shop",
                "doc_type": "code",
                "rel_path": "Services/ProductQueryBuilder.cs",
                "symbol": "ProductQueryBuilder.ExcludeDiscontinued",
                "language": "c_sharp",
                "content": "public IQueryable<Product> ExcludeDiscontinued(IQueryable<Product> q) => q;",
            },
        },
    ]
    lexical_result = MagicMock()
    lexical_result.mappings.return_value.fetchall.return_value = [
        {
            "id": "fixture-summary",
            "sparse_score": 1.00,
            "payload": {
                "repo": "shop",
                "doc_type": "summary",
                "is_summary": True,
                "rel_path": "cypress/fixtures/product-catalog.html",
                "content": "Summary of cypress/fixtures/product-catalog.html containing product filter fixtures",
            },
        },
        {
            "id": "css-static",
            "sparse_score": 0.95,
            "payload": {
                "repo": "shop",
                "doc_type": "code",
                "rel_path": "wwwroot/products/static.css",
                "language": "css",
                "content": ".product-filter-active { display: block; }",
            },
        },
        {
            "id": "minified-js",
            "sparse_score": 0.90,
            "payload": {
                "repo": "shop",
                "doc_type": "code",
                "rel_path": "wwwroot/dist/vendor.min.js",
                "language": "javascript",
                "content": "var productFilter=function(){};",
            },
        },
        {
            "id": "lex-only-unrelated",
            "sparse_score": 0.85,
            "payload": {
                "repo": "shop",
                "doc_type": "code",
                "rel_path": "Prompts/CatalogPromptBuilder.cs",
                "symbol": "CatalogPromptBuilder.Build",
                "language": "c_sharp",
                "content": "const string prompt = \"filter discontinued product\";",
            },
        },
        {
            "id": "cs-dual",
            "sparse_score": 0.62,
            "payload": {
                "repo": "shop",
                "doc_type": "code",
                "rel_path": "Services/CatalogFilter.cs",
                "symbol": "CatalogFilter.ApplyVisibilityRules",
                "language": "c_sharp",
                "content": "public IQueryable<Product> ApplyVisibilityRules(IQueryable<Product> q) => q;",
            },
        },
    ]
    mock_conn.execute.side_effect = [dense_result, lexical_result]

    with patch("app.services.vector_store.pgvector_store.get_dense_dim", return_value=4), \
         patch("app.services.vector_store.pgvector_store.get_dense_embedding", return_value=[0.5, 0.5, 0.5, 0.5]):
        store = PgVectorStore(engine=mock_engine, dimension=4, auto_init=False)
        results = store.search(
            query_text="filter discontinued products from catalog availability",
            search_mode="hybrid",
            limit=6,
        )

    ids = [r.id for r in results]
    assert ids[0] == "cs-dual"
    assert ids[1] == "cs-dense-only"
    by_id = {r.id: r for r in results}
    assert by_id["cs-dense-only"].score > by_id["lex-only-unrelated"].score
    assert by_id["cs-dense-only"].score > by_id["fixture-summary"].score
    assert by_id["cs-dense-only"].score > by_id["css-static"].score
    assert by_id["cs-dense-only"].score > by_id["minified-js"].score


def test_qdrant_hybrid_ranks_semantic_code_above_lexical_only_fixture_and_css():
    """Qdrant hybrid fusion must dampen lexical-only hits and demote fixture/CSS/summary noise."""
    mock_client = MagicMock()
    mock_client.collection_exists.return_value = True
    col_info = MagicMock()
    dense_cfg = MagicMock()
    dense_cfg.size = 4
    col_info.config.params.vectors = {"dense": dense_cfg}
    mock_client.get_collection.return_value = col_info

    dense_hits = MagicMock()
    dense_hits.points = [
        _mock_qdrant_point(
            "cs-dense",
            0.58,
            {
                "repo": "shop",
                "doc_type": "code",
                "rel_path": "Services/ProductFilter.cs",
                "symbol": "ProductFilter.IsVisible",
                "language": "c_sharp",
            },
        ),
    ]
    sparse_hits = MagicMock()
    sparse_hits.points = [
        _mock_qdrant_point(
            "fixture-html",
            10.0,
            {
                "repo": "shop",
                "doc_type": "summary",
                "is_summary": True,
                "rel_path": "cypress/fixtures/catalog.html",
            },
        ),
        _mock_qdrant_point(
            "css-file",
            9.5,
            {
                "repo": "shop",
                "doc_type": "code",
                "rel_path": "web/products/static.css",
                "language": "css",
            },
        ),
        _mock_qdrant_point(
            "lex-only-code",
            9.0,
            {
                "repo": "shop",
                "doc_type": "code",
                "rel_path": "Prompts/OtherClass.cs",
                "symbol": "OtherClass.Text",
                "language": "c_sharp",
            },
        ),
    ]
    mock_client.query_batch_points.return_value = [dense_hits, sparse_hits]

    sparse_vec = MagicMock()
    sparse_vec.indices = [1, 2, 3]
    sparse_vec.values = [1.0, 0.8, 0.5]

    results = execute_qdrant_search(
        client=mock_client,
        collection_name="test_coll",
        supported_modes=["hybrid", "semantic", "lexical"],
        dense_embed_fn=lambda _: [0.5, 0.5, 0.5, 0.5],
        sparse_embed_fn=lambda _: sparse_vec,
        query_text="how are discontinued products filtered out of the catalog?",
        doc_type="code",
        limit=5,
        search_mode="hybrid",
    )

    assert results[0].id == "cs-dense"
    by_id = {r.id: r for r in results}
    assert by_id["cs-dense"].score > by_id["lex-only-code"].score
    assert by_id["cs-dense"].score > by_id["fixture-html"].score
    assert by_id["cs-dense"].score > by_id["css-file"].score


def test_execute_hybrid_search_uses_expanded_candidate_pool_before_fusion():
    """execute_hybrid_search must fetch a >=5x candidate pool from Track A and Track B before fusing down to limit."""
    captured = {}

    class _FakeStore:
        mode = "remote"

        def get_capabilities(self):
            return {"search_modes": ["hybrid", "semantic", "lexical"]}

        def search(self, **kwargs):
            captured["track_b_limit"] = kwargs["limit"]
            return [
                VectorSearchResult(
                    id="sem-code",
                    score=0.56,
                    dense_score=0.56,
                    sparse_score=0.0,
                    dense_rank=1,
                    payload={
                        "repo": "shop",
                        "doc_type": "code",
                        "rel_path": "Services/CatalogVisibility.cs",
                        "symbol": "CatalogVisibility.FilterActive",
                        "language": "c_sharp",
                        "content": "public bool FilterActive(Product p) => !p.IsDiscontinued;",
                    },
                ),
            ]

    def _fake_track_a(**kwargs):
        captured["track_a_limit"] = kwargs["limit"]
        return [
            VectorSearchResult(
                id="lex-fixture",
                score=0.92,
                dense_score=0.0,
                sparse_score=0.92,
                sparse_rank=1,
                payload={
                    "repo": "shop",
                    "doc_type": "code",
                    "rel_path": "cypress/fixtures/products.html",
                    "content": "<div>filter active catalog discontinued</div>",
                },
            ),
            VectorSearchResult(
                id="lex-css",
                score=0.88,
                dense_score=0.0,
                sparse_score=0.88,
                sparse_rank=2,
                payload={
                    "repo": "shop",
                    "doc_type": "code",
                    "rel_path": "wwwroot/products/static.css",
                    "language": "css",
                    "content": ".catalog-filter-active { color: red; }",
                },
            ),
        ]

    with patch("app.services.search.get_vector_store", return_value=_FakeStore()), \
         patch("app.services.search.run_fast_lexical_track", side_effect=_fake_track_a), \
         patch("app.services.search._enrich_code_ast_metadata"):
        results = execute_hybrid_search(
            "how does catalog visibility filter discontinued products?",
            doc_type="code",
            repo="shop",
            limit=5,
        )

    assert captured["track_b_limit"] >= 25
    assert captured["track_a_limit"] >= 25
    assert len(results) <= 5
    assert results[0].id == "sem-code"


def test_explicit_css_query_does_not_demote_css_files():
    """Demotion of CSS/fixture assets must back off when the query explicitly asks for CSS or fixtures."""
    css_hit = VectorSearchResult(
        id="css-1",
        score=0.80,
        dense_score=0.60,
        sparse_score=1.0,
        payload={
            "repo": "web",
            "doc_type": "code",
            "rel_path": "wwwroot/products/static.css",
            "language": "css",
            "content": ".product-card { margin: 8px; }",
        },
    )
    code_hit = VectorSearchResult(
        id="cs-1",
        score=0.60,
        dense_score=0.60,
        sparse_score=0.60,
        payload={
            "repo": "web",
            "doc_type": "code",
            "rel_path": "Services/ProductCard.cs",
            "language": "c_sharp",
            "content": "public class ProductCard {}",
        },
    )

    non_css_fused = fuse_search_results(
        [], [css_hit, code_hit], limit=5, intent="semantic_prose",
        query_text="how are product cards filtered in the backend?", doc_type="code",
    )
    assert non_css_fused[0].id == "cs-1"

    explicit_css_fused = fuse_search_results(
        [], [css_hit, code_hit], limit=5, intent="semantic_prose",
        query_text="product card margin styling in static.css stylesheet", doc_type="code",
    )
    assert explicit_css_fused[0].id == "css-1"


def test_early_return_skipped_for_low_signal_track_a_hits():
    """should_early_return_lexical must not short-circuit Track B when the top Track A hit is a fixture or CSS file."""
    plan = classify_query_intent("product filter active status")
    assert plan.intent == "lexical_keywords"
    fixture_hit = VectorSearchResult(
        id="fix-1",
        score=0.95,
        dense_score=0.0,
        sparse_score=0.95,
        payload={
            "repo": "shop",
            "doc_type": "code",
            "rel_path": "cypress/fixtures/products.html",
            "content": "product filter active status",
            "_lexical_meta": {"coverage": 1.0, "header_hits": 1, "body_hits": 4, "matched_count": 4},
        },
    )
    assert should_early_return_lexical(plan, [fixture_hit], doc_type="code") is False


@pytest.fixture
def diag_db(tmp_path, monkeypatch):
    db_file = tmp_path / "diag_188.db"
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", str(db_file))
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", str(db_file), raising=False)
    init_db(engine=get_db_engine(db_url, reset=True))
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language) "
            "VALUES ('shop', 'shop://Services/CatalogFilter.cs', 'ApplyFilter', 'CatalogFilter.ApplyFilter', 'method_declaration', 10, 30, 'ApplyFilter()', 'c_sharp')"
        )
        conn.commit()


def _diag_hit(rel_path: str, score: float, *, doc_type: str = "code", language: str = "c_sharp", symbol: str = None, is_summary: bool = False):
    hit = MagicMock()
    hit.score = score
    hit.payload = {
        "repo": "shop",
        "doc_type": doc_type,
        "is_summary": is_summary,
        "rel_path": rel_path,
        "start_line": 1,
        "end_line": 20,
        "symbol": symbol,
        "full_symbol": symbol,
        "kind": "method" if symbol else None,
        "language": language,
        "content": "...",
    }
    return hit


def test_diagnose_issue_plain_language_uses_higher_dense_weight_expanded_pool_and_filters_noise(diag_db):
    """Plain-language bug reports (even with part numbers/UI labels) must boost dense_weight, expand limit, and drop CSS/fixtures/summaries."""
    issue = (
        "Users report that part number 1234-ABCD and MegaWidget Pro still appear when the "
        "'In Stock Only' filter toggle is checked on the storefront catalog page."
    )
    mixed_hits = [
        _diag_hit("wwwroot/products/static.css", 0.50, language="css"),
        _diag_hit("cypress/fixtures/catalog.html", 0.49, doc_type="summary", language="html", is_summary=True),
        _diag_hit("wwwroot/dist/app.min.js", 0.48, language="javascript"),
        _diag_hit("Services/CatalogFilter.cs", 0.46, language="c_sharp", symbol="CatalogFilter.ApplyFilter"),
    ]

    with patch("app.services.diagnostics.execute_hybrid_search", return_value=mixed_hits) as mock_search:
        result = diagnose_issue(issue, repo="shop", limit=5)

    mock_search.assert_called_once()
    kwargs = mock_search.call_args.kwargs
    assert kwargs["limit"] >= 25
    assert kwargs.get("dense_weight") is not None and kwargs["dense_weight"] >= 0.75

    cands = result["semantic_candidates"]
    assert [c["file"] for c in cands] == ["Services/CatalogFilter.cs"]


def test_diagnose_issue_with_matched_code_symbol_keeps_balanced_hybrid_weight(diag_db):
    """When concrete indexed symbols or exceptions are present, diagnose_issue keeps default balanced hybrid weight."""
    issue = "CatalogFilter.ApplyFilter throws NullReferenceException when catalog filters are empty."
    with patch("app.services.diagnostics.execute_hybrid_search", return_value=[]) as mock_search:
        diagnose_issue(issue, repo="shop", limit=5)

    mock_search.assert_called_once()
    kwargs = mock_search.call_args.kwargs
    assert kwargs["limit"] >= 25
    assert kwargs.get("dense_weight") is None


def test_keep_semantic_hit_drops_css_fixtures_minified_and_summaries_but_keeps_extensionless():
    assert not keep_semantic_hit({"repo": "shop", "rel_path": "products/static.css", "language": "css"}, "shop", set())
    assert not keep_semantic_hit({"repo": "shop", "rel_path": "cypress/fixtures/page.html", "language": "html"}, "shop", set())
    assert not keep_semantic_hit({"repo": "shop", "rel_path": "dist/bundle.min.js", "language": "javascript"}, "shop", set())
    assert not keep_semantic_hit({"repo": "shop", "rel_path": "Services/Big.cs", "doc_type": "summary", "is_summary": True}, "shop", set())
    assert keep_semantic_hit({"repo": "shop", "rel_path": "products/static.css", "language": "css"}, "shop", set(), query_text="CSS layout broken in static.css")
    assert keep_semantic_hit({"repo": "shop", "rel_path": "notes"}, "shop", {"csharp"})
