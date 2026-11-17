"""trace_path with an unknown class returns found: false and candidates, not the merged graph of every same-named method."""

import asyncio
import json

from app.mcp.handlers.symbol_handlers import handle_trace_path
from tests.test_diagnose_evidence_chain import REPO, chain_db  # noqa: F401  (pytest fixture)


def _trace(symbol, **kwargs):
    return json.loads(asyncio.run(handle_trace_path(symbol=symbol, repo=REPO, direction="both", depth=2, **kwargs)))


def test_unknown_class_gives_candidates_and_no_merged_graph(chain_db):  # noqa: F811
    result = _trace("WrongReader.GetByInstanceId")
    assert result["found"] is False and result["callers"] == [] and result["callees"] == []
    assert "target" not in result
    assert {c["symbol"] for c in result["candidates"]} >= {"ToolReader.GetByInstanceId", "ToolService.GetByInstanceId"}
    assert all(not c["file"].startswith(("/", "C:")) and ":" not in c["file"] for c in result["candidates"])
    assert "WrongReader.GetByInstanceId" in result["hint"]


def test_known_names_still_trace(chain_db):  # noqa: F811
    qualified = _trace("ToolReader.GetByInstanceId")
    assert qualified["target"]["symbol"] == "ToolReader.GetByInstanceId" and qualified["callees"]
    bare = _trace("GetAccess")
    assert bare.get("found") is not False and bare["target"]["symbol"].endswith("GetAccess")


def test_unknown_bare_name_has_no_candidates(chain_db):  # noqa: F811
    result = _trace("NoSuchMethodAnywhere")
    assert result["found"] is False and "candidates" not in result
