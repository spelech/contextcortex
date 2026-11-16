"""diagnose_issue is compact by default; detail=true gives candidate code and full relation lists."""

import json
from unittest.mock import patch

import pytest

from app.mcp.handlers.diagnostic_handlers import handle_diagnose_issue
from app.services.diagnostic_output import COMPACT_MAX_RELATIONS, compact_diagnosis
from app.services.diagnostics import diagnose_issue
from tests.test_diagnose_repo_filter_route_candidates import ISSUE, NOISE_HITS, REPO, hub_db  # noqa: F401


def _run(**kwargs):
    with patch("app.services.diagnostics.execute_hybrid_search", return_value=NOISE_HITS), \
         patch("app.services.diagnostics.read_symbol_code", return_value="public void PublishInstance() {}") as reader:
        return diagnose_issue(ISSUE, repo=REPO, limit=5, **kwargs), reader


def test_default_candidates_have_no_code_and_keep_leads(hub_db):
    result, reader = _run()
    reader.assert_not_called()
    cands = result["semantic_candidates"]
    assert [c["symbol"] for c in cands][:3] == [
        "ToolsController.PublishInstance", "ToolService.PublishInstance", "ToolRepository.PublishInstance",
    ]
    for c in cands:
        assert "content" not in c
        assert c["file"] and c["lines"] and c["source"]
    assert result["matched_routes"][0]["handler"]["symbol"] == "ToolsController.PublishInstance"
    assert "detail=true" in result["hint"]


def test_detail_returns_candidate_code_and_no_hint(hub_db):
    result, reader = _run(detail=True)
    assert reader.call_count == 3
    cands = result["semantic_candidates"]
    assert all("content" in c for c in cands)
    assert cands[0]["content"] == "public void PublishInstance() {}"
    assert "hint" not in result


def test_compact_cuts_relation_lists_but_keeps_frame_code():
    many = [{"symbol": f"S{i}"} for i in range(10)]
    result = compact_diagnosis({
        "resolved_frames": [{"code": "line", "callers": list(many), "callees": list(many)}],
        "matched_routes": [{"external_callers": list(many)}],
        "matched_symbols": [],
        "semantic_candidates": [{"callers": ["a", "b", "c", "d"], "callees": []}],
    })
    frame = result["resolved_frames"][0]
    assert frame["code"] == "line"
    assert len(frame["callers"]) == len(frame["callees"]) == COMPACT_MAX_RELATIONS
    assert len(result["matched_routes"][0]["external_callers"]) == COMPACT_MAX_RELATIONS
    assert result["semantic_candidates"][0]["callers"] == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_handler_passes_detail_and_returns_unindented_json(hub_db):
    with patch("app.services.diagnostics.execute_hybrid_search", return_value=NOISE_HITS):
        compact = await handle_diagnose_issue(ISSUE, repo=REPO)
        detailed = await handle_diagnose_issue(ISSUE, repo=REPO, detail=True)
    assert "\n" not in compact
    assert "content" not in json.loads(compact)["semantic_candidates"][0]
    assert "content" in json.loads(detailed)["semantic_candidates"][0]
    assert "hint" in json.loads(compact) and "hint" not in json.loads(detailed)
