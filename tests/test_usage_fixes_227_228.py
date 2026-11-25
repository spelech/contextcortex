"""Regression tests for Issues #227 and #228: prose-slash route false positives, transient LLM retries, fallback cache hygiene, per-round status, and LLM stats."""

import asyncio
import json
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.mcp.handlers.search_handlers import handle_search
from app.services.database.engine import get_db_engine, init_db
from app.services.diagnostics import diagnose_issue
from app.services.expanded_search import run_expanded_code_search, should_auto_expand_search_query
from app.services.llm_client import create_chat_completion, get_llm_call_stats, reset_model_capabilities
from app.services.query_expansion import clear_expansion_cache, expand_report_to_code_queries
from app.services.stack_trace_parser import extract_diagnostic_signals, extract_http_routes
from app.services.vector_store.base import VectorSearchResult


@pytest.fixture
def clean_env(tmp_path, monkeypatch):
    clear_expansion_cache()
    reset_model_capabilities()
    db_file = tmp_path / "issue_227_228.db"
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.delenv("CHAT_MODEL", raising=False)
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", str(db_file))
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", str(db_file), raising=False)
    init_db(engine=get_db_engine(db_url, reset=True))
    yield tmp_path
    clear_expansion_cache()
    reset_model_capabilities()


def _hit(hit_id: str, path: str, symbol: str, score: float, content: str) -> VectorSearchResult:
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
            "start_line": 10,
            "end_line": 40,
            "content": content,
        },
    )


# --- Issue #227: prose slashes (in/is, and/or, iOS/Android, 1/2) must not trigger route detection ---


@pytest.mark.parametrize(
    "report",
    [
        "When the filter is cleared the item pops back in/is visible on the catalog listing.",
        "the order total is wrong and/or the tax is missing",
        "users on iOS/Android see an empty cart",
        "the price shows 0 when quantity is 1/2 box",
    ],
)
def test_227_prose_slashes_are_not_routes_and_auto_expand_triggers(report):
    assert extract_http_routes(report) == []
    assert extract_diagnostic_signals(report)["routes"] == []
    assert should_auto_expand_search_query(report, "code") is True


def test_227_real_http_routes_still_detected_and_skip_auto_expand(clean_env):
    assert extract_http_routes("GET /health returned 503") == [("GET", "/health")]
    assert extract_http_routes("POST https://api.example.com/v2/orders failed") == [("POST", "/v2/orders")]
    assert extract_http_routes("Request to https://shop.example.com/cart failed") == [(None, "/cart")]
    assert extract_http_routes("Endpoint /api/orders failed with 500") == [(None, "/api/orders")]
    assert extract_http_routes("Endpoint '/items/{id}' returned empty") == [(None, "/items/{id}")]
    assert extract_http_routes("File /status.json returned invalid payload") == [(None, "/status.json")]
    assert extract_http_routes("Call /search?q=widget timed out") == [(None, "/search")]

    # Real routes still suppress plain-language auto-expand
    assert should_auto_expand_search_query("Users calling /api/orders get an empty list when filtering by date.", "code") is False
    assert should_auto_expand_search_query("GET /health fails intermittently after deploy when database restarts.", "code") is False

    # diagnose_issue with prose slash (`in/is`) must NOT trigger route lookup
    with patch("app.services.diagnostics.match_routes_and_callers", side_effect=AssertionError("should not be called with routes")) as mock_routes:
        # match_routes_and_callers IS called with empty list [], verify it receives []
        pass
    with patch("app.services.diagnostics.match_routes_and_callers", return_value=[]) as mock_routes, \
         patch("app.services.diagnostics.execute_hybrid_search", return_value=[]):
        diagnose_issue("The accessory pops back in/is visible when the spec filter is toggled.", repo="shop")
    mock_routes.assert_called_once_with([], repo="shop")


# --- Issue #228: transient retry, no caching fallback under LLM key, skip noisy round-2 fallback, per-round status & stats ---


def test_228_transient_503_retries_once_and_round1_fallback_not_cached_under_llm_key(clean_env, monkeypatch):
    monkeypatch.setenv("CHAT_MODEL", "openai/o3-mini")

    # 1. Transient 503 followed by success recovers automatically on retry!
    attempts = {"n": 0}

    class _FlakyClient:
        class _Completions:
            @staticmethod
            def create(**_kwargs):
                attempts["n"] += 1
                if attempts["n"] == 1:
                    raise RuntimeError("Error code: 503 - Service Temporarily Unavailable")
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content='["related product inline", "master part rule", "spec filter view"]'))]
                )

        chat = SimpleNamespace(completions=_Completions())

    with patch("app.services.llm_client.time.sleep") as mock_sleep, \
         patch("app.services.query_expansion._build_llm_client", return_value=_FlakyClient()):
        q_ok, src_ok = expand_report_to_code_queries("Linked accessory missing on catalog page unless filtered.", repo="shop")
    assert src_ok == "llm" and len(q_ok) == 3 and attempts["n"] == 2
    mock_sleep.assert_called_once()

    # 2. If both attempts fail, fallback heuristic is NOT cached under the LLM key; next call succeeds with LLM!
    clear_expansion_cache()
    always_503 = MagicMock()
    always_503.chat.completions.create.side_effect = RuntimeError("Error code: 503 - still down")
    report = "Accessory missing for product on default listing, but visible when filtered by spec."
    with patch("app.services.llm_client.time.sleep"), \
         patch("app.services.query_expansion._build_llm_client", return_value=always_503):
        q_fb, src_fb = expand_report_to_code_queries(report, repo="shop")
    assert src_fb == "heuristic" and q_fb

    recovered = MagicMock()
    recovered.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='["related products inline", "master part exclusion", "spec filter visibility"]'))]
    )
    with patch("app.services.query_expansion._build_llm_client", return_value=recovered):
        q_rec, src_rec = expand_report_to_code_queries(report, repo="shop")
    assert src_rec == "llm" and q_rec == ["related products inline", "master part exclusion", "spec filter visibility"]
    assert recovered.chat.completions.create.call_count == 1


def test_228_round2_llm_failure_skips_noisy_symbol_fallback_and_reports_per_round_status(clean_env, monkeypatch):
    monkeypatch.setenv("CHAT_MODEL", "openai/o3-mini")

    r1_resp = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='["related products inline", "primary product lookup", "spec filter items"]'))]
    )
    client = MagicMock()
    # Call 1 (round 1) succeeds; calls 2 & 3 (round 2 + its 1 transient retry) fail with 503.
    client.chat.completions.create.side_effect = [
        r1_resp,
        RuntimeError("Error code: 503 - upstream overloaded"),
        RuntimeError("Error code: 503 - upstream overloaded"),
    ]

    r1_hit = _hit("rb1", "Services/RelatedItems/RelatedItemsBuilder.cs", "RelatedItemsBuilder.Build", 0.88, "if (master == related) remove();")
    search_calls = []

    def _fake_search(query_text: str, **_kw):
        search_calls.append(query_text)
        return [r1_hit]

    report = "An accessory does not show inline for a product on the catalog page, but shows when filtered by spec."
    with patch("app.services.llm_client.time.sleep"), \
         patch("app.services.query_expansion._build_llm_client", return_value=client):
        outcome = run_expanded_code_search(report, search_fn=_fake_search, repo="shop", limit=6)

    # Round 2 must be skipped cleanly (no noisy symbol-phrase searches!) and status must show round1=llm, round2=skipped.
    assert outcome.expansion == {"round1": "llm", "round2": "skipped"}
    assert len(search_calls) == 3
    assert all(q["round"] == 1 and q["source"] == "llm" for q in outcome.queries)
    assert outcome.areas[0]["file"] == "Services/RelatedItems/RelatedItemsBuilder.cs"


def test_228_llm_failure_counters_logged_and_exposed_in_admin_stats(clean_env, monkeypatch, caplog):
    import main as main_mod

    monkeypatch.setenv("CHAT_MODEL", "openai/flaky-model")
    failing_client = MagicMock()
    failing_client.chat.completions.create.side_effect = RuntimeError("Error code: 503 - overloaded")

    with caplog.at_level(logging.INFO, logger="contextcortex.query_expansion"), \
         patch("app.services.llm_client.time.sleep"), \
         patch("app.services.query_expansion._build_llm_client", return_value=failing_client):
        expand_report_to_code_queries("First report about missing inline accessory.", repo="shop")
        expand_report_to_code_queries("Second report about missing inline accessory.", repo="shop")

    # First failure logged at WARNING, second logged at INFO with failure/call ratio (never hidden at DEBUG).
    assert any(r.levelno == logging.WARNING and "openai/flaky-model" in r.message for r in caplog.records)
    assert any(r.levelno == logging.INFO and "failures/calls" in r.message for r in caplog.records)

    stats_map = get_llm_call_stats()
    assert stats_map["openai/flaky-model"]["calls"] == 2
    assert stats_map["openai/flaky-model"]["failures"] == 2
    assert stats_map["openai/flaky-model"]["retries"] == 2

    res = TestClient(main_mod.app).get("/admin/api/stats")
    assert res.status_code == 200
    body = res.json()
    assert "llm_stats" in body
    assert body["llm_stats"]["openai/flaky-model"]["failures"] == 2
