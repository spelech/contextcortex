"""Regression tests for Issues #222, #223, and #224: chat completion compatibility, round-2 corpus grounding & per-query slots, and search auto-expansion."""

import asyncio
import json
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.mcp.handlers.search_handlers import handle_search
from app.mcp.mcp_server import build_mcp_server_instructions
from app.mcp.tools import get_tool_definitions
from app.services.database.engine import get_db_engine, init_db
from app.services.diagnostics import diagnose_issue
from app.services.expanded_search import run_expanded_code_search, should_auto_expand_search_query
from app.services.llm_client import create_chat_completion, reset_model_capabilities
from app.services.pdf_extractor import _call_vision_ocr
from app.services.query_expansion import clear_expansion_cache, expand_report_to_code_queries
from app.services.vector_store.base import VectorSearchResult


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    clear_expansion_cache()
    reset_model_capabilities()
    db_file = tmp_path / "issue_222_224.db"
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.delenv("CHAT_MODEL", raising=False)
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", str(db_file))
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", str(db_file), raising=False)
    init_db(engine=get_db_engine(db_url, reset=True))
    yield tmp_path
    clear_expansion_cache()
    reset_model_capabilities()


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


# --- Issue #222: temperature / max_tokens compatibility, shared helper, once-per-model logging, `expansion` field ---


def test_222_llm_expansion_omits_temperature_and_retries_400_for_reasoning_models(isolated_env, monkeypatch):
    monkeypatch.setenv("CHAT_MODEL", "openai/o3-mini")
    calls = []

    class _StrictReasoningClient:
        class _Completions:
            @staticmethod
            def create(**kwargs):
                calls.append(dict(kwargs))
                if "temperature" in kwargs:
                    raise RuntimeError(
                        "Error code: 400 - Unsupported value: 'temperature' does not support 0.1 with this model."
                    )
                if "max_tokens" in kwargs:
                    raise RuntimeError(
                        "Error code: 400 - Unsupported parameter: 'max_tokens' is not supported with this model. Use 'max_completion_tokens' instead."
                    )
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content='["related products inline visibility", "master part lookup exclusion", "spec filter item display"]'
                            )
                        )
                    ]
                )

        chat = SimpleNamespace(completions=_Completions())

    strict_client = _StrictReasoningClient()
    with patch("app.services.query_expansion._build_llm_client", return_value=strict_client):
        queries, source = expand_report_to_code_queries(
            "Linked accessory is missing inline for an item unless a spec filter is active.", repo="shop"
        )

    assert source == "llm"
    assert len(queries) == 3
    assert len(calls) == 1
    assert "temperature" not in calls[0]

    # Direct create_chat_completion with temperature + max_tokens retries & remembers per-model capabilities.
    calls.clear()
    create_chat_completion(
        strict_client, model="openai/o3-mini", messages=[{"role": "user", "content": "hi"}], temperature=0.1, max_tokens=512
    )
    assert len(calls) == 3  # 1st rejects temperature, 2nd rejects max_tokens, 3rd succeeds with max_completion_tokens
    assert "temperature" not in calls[-1]
    assert "max_tokens" not in calls[-1]
    assert calls[-1]["max_completion_tokens"] == 512

    # Subsequent call on the same model goes straight to compatible args in 1 attempt (remembered).
    calls.clear()
    create_chat_completion(
        strict_client, model="openai/o3-mini", messages=[{"role": "user", "content": "hi2"}], temperature=0.0, max_tokens=256
    )
    assert len(calls) == 1
    assert "temperature" not in calls[0] and calls[0]["max_completion_tokens"] == 256

    # Vision OCR also uses create_chat_completion and handles reasoning models rejecting max_tokens.
    calls.clear()
    with patch("app.services.pdf_extractor.OpenAI", return_value=strict_client):
        text = _call_vision_ocr(b"\x89PNG", model_name="openai/o3-mini")
    assert text and "temperature" not in calls[0] and calls[0]["max_completion_tokens"] == 4096


def test_222_llm_failure_logs_once_per_model_and_reports_expansion_mode(isolated_env, monkeypatch, caplog):
    monkeypatch.setenv("CHAT_MODEL", "broken-model")
    failing_client = MagicMock()
    failing_client.chat.completions.create.side_effect = RuntimeError("Error code: 500 - gateway down")

    with caplog.at_level(logging.WARNING, logger="contextcortex.query_expansion"), \
         patch("app.services.query_expansion._build_llm_client", return_value=failing_client):
        q1, src1 = expand_report_to_code_queries("Accessory missing on catalog page when no filter is set.", repo="shop")
        q2, src2 = expand_report_to_code_queries("Second different bug report about product filter visibility.", repo="shop")

    assert src1 == "heuristic" and src2 == "heuristic" and q1 and q2
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and "broken-model" in r.message]
    assert len(warnings) == 1

    # Both diagnose_issue and search(expand=True) expose `expansion: "heuristic" | "llm"`.
    hit = _hit("h1", "Services/Catalog/Filter.cs", "Filter.Run", 0.8, "if (active) return items;")
    with patch("app.services.query_expansion._build_llm_client", return_value=failing_client), \
         patch("app.services.diagnostics.execute_hybrid_search", return_value=[hit]), \
         patch("app.mcp.tools.execute_hybrid_search", return_value=[hit]):
        diag = diagnose_issue("Accessory missing inline on catalog page unless spec filter is applied.", repo="shop")
        srch = json.loads(asyncio.run(handle_search(
            query="Accessory missing inline on catalog page unless spec filter is applied.", scope="code", repo="shop", expand=True
        )))
    assert diag["expansion"] == "heuristic"
    assert srch["expansion"] == "heuristic" and srch["expanded"] is True


# --- Issue #223: corpus-grounded round 2 from round-1 symbol names + best-of-each-query slot ---


def test_223_round2_grounds_in_round1_symbols_and_reaches_rule_file(isolated_env):
    report = (
        "A linked accessory is missing for an item on the default search path, "
        "but becomes visible when a filtered search path is used."
    )
    sibling_hit = _hit(
        "sib1",
        "Services/RelatedItems/RelatedProductMap.cs",
        "RelatedProductMap.BuildRelatedProductsByPrimaryPartNumber",
        0.82,
        "public Dictionary<string, List<Related>> BuildRelatedProductsByPrimaryPartNumber() => map;",
        20,
        55,
    )
    rule_hit = _hit(
        "rule1",
        "Services/RelatedItems/RelatedProductRuleBuilder.cs",
        "RelatedProductRuleBuilder.RemoveRedundantRelatedItems",
        0.93,
        "if (masterPart == relatedPart || lookup.ContainsKey(masterPart)) items.Remove(related);",
        72,
        148,
    )

    def _fake_search(query_text: str, **_kw):
        q = query_text.lower()
        # Only a round-2 query grounded in "related" + "primary" / "part" finds the rule file!
        if "related" in q and ("primary" in q or "part" in q):
            return [rule_hit, sibling_hit]
        return [sibling_hit]

    outcome = run_expanded_code_search(report, search_fn=_fake_search, repo="shop", limit=6)
    rounds = {q["round"] for q in outcome.queries}
    assert rounds == {1, 2}
    r2_texts = [q["query"] for q in outcome.queries if q["round"] == 2]
    assert any("related" in q and ("primary" in q or "part" in q) for q in r2_texts)
    assert any(a["file"] == "Services/RelatedItems/RelatedProductRuleBuilder.cs" for a in outcome.areas)


def test_223_best_of_each_query_slot_preserves_strong_single_query_hit(isolated_env):
    # 12 consensus noise files appear across queries 0, 1, 2; query 3 uniquely ranks the rule file #1!
    consensus_hits = [
        _hit(f"c{i}", f"Services/Area{i}/Noise{i}.cs", f"Noise{i}.Run", 0.70 - i * 0.01, f"return noise{i}();")
        for i in range(12)
    ]
    precise_rule = _hit(
        "rule",
        "Services/Rules/RelatedMasterRule.cs",
        "RelatedMasterRule.Evaluate",
        0.95,
        "if (master == related) items.Remove(component);",
        40,
        90,
    )

    seen_calls = []

    def _fake_search(query_text: str, **_kw):
        idx = len(seen_calls)
        seen_calls.append(query_text)
        if idx == 2:
            return [precise_rule]
        return list(consensus_hits)

    report = "Linked accessory missing inline on catalog page, but visible when filtered by spec value."
    outcome = run_expanded_code_search(
        report, search_fn=_fake_search, repo="shop", limit=6, area_limit=8, enable_round2=False
    )

    area_files = [a["file"] for a in outcome.areas]
    assert "Services/Rules/RelatedMasterRule.cs" in area_files


# --- Issue #224: auto-expand plain-language queries in search & consistent guidance across all 3 places ---


def test_224_search_auto_expands_plain_language_reports_and_respects_expand_false(isolated_env):
    long_report = (
        "An accessory does not show inline for one product on one catalog page, "
        "but shows when the page is filtered by a spec value."
    )
    two_sentence_report = "The linked accessory is missing on the listing. It reappears when a filter is applied."

    assert should_auto_expand_search_query(long_report, "code") is True
    assert should_auto_expand_search_query(two_sentence_report, "all") is True
    assert should_auto_expand_search_query("related products inline", "code") is False
    assert should_auto_expand_search_query("RelatedItemsBuilder.Build", "code") is False
    assert should_auto_expand_search_query(long_report, "docs") is False

    hit = _hit("rb1", "Services/RelatedItems/RelatedItemsBuilder.cs", "RelatedItemsBuilder.Build", 0.85, "if (master == related) remove();")
    with patch("app.mcp.tools.execute_hybrid_search", return_value=[hit]) as mock_search:
        auto_res = json.loads(asyncio.run(handle_search(query=long_report, scope="code", repo="shop")))
        disabled_res = json.loads(asyncio.run(handle_search(query=long_report, scope="code", repo="shop", expand=False)))
        short_res = json.loads(asyncio.run(handle_search(query="related products", scope="code", repo="shop")))

    assert auto_res["expanded"] is True
    assert auto_res["expansion"] == "heuristic"
    assert len(auto_res["queries"]) >= 3 and auto_res["areas"]
    assert "expanded" not in disabled_res and "queries" not in disabled_res
    assert "expanded" not in short_res and "queries" not in short_res
    assert mock_search.call_count == len(auto_res["queries"]) + 2


def test_224_instructions_and_tool_descriptions_align_on_search_expansion():
    instructions = build_mcp_server_instructions()
    tool_descs = {name: desc for name, _fn, desc in get_tool_definitions()}

    for text in (instructions, tool_descs["diagnose_issue"], tool_descs["search"], tool_descs["execute_script"]):
        assert "expand=true" in text.lower() or "auto-expand" in text.lower()
