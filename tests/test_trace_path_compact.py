"""Tests that trace_path answers stay compact: no per-node permalinks unless include_permalinks=True."""

import asyncio
import json
from unittest.mock import patch

import app.mcp.tools  # noqa: F401  (registers the module that _get_tools_attr reads)
from app.mcp.handlers.symbol_handlers import handle_trace_path

LINK = "https://git.example.com/group/project/-/blob/0123456789abcdef0123456789abcdef01234567/src/Engine.cs#L10-L20"


def _fake_trace(**_kwargs):
    node = lambda name, children=None: {
        "symbol": name, "rel": "CALLS", "repo": "r", "file": "src/Engine.cs", "line": 10,
        "permalink": LINK, "callees": children or [],
    }
    return {
        "target": {"symbol": "Engine.Run", "repo": "r", "file": "src/Engine.cs", "lines": [10, 20], "permalink": LINK},
        "direction": "both", "depth": 2,
        "callers": [node("Api.Analyze")],
        "callees": [node("Engine.Preprocess", [node("Ledger.Load")]), node("Rules.Classify")],
    }


def _run(**kwargs):
    with patch("app.mcp.tools.trace_symbol_path", side_effect=_fake_trace):
        return json.loads(asyncio.run(handle_trace_path(symbol="Engine.Run", **kwargs)))


def test_trace_nodes_have_no_permalinks_by_default_but_the_target_keeps_one():
    result = _run()
    assert result["target"]["permalink"] == LINK
    dumped = json.dumps(result["callers"] + result["callees"])
    assert "permalink" not in dumped
    assert [n["symbol"] for n in result["callees"]] == ["Engine.Preprocess", "Rules.Classify"]
    assert result["callees"][0]["callees"][0]["symbol"] == "Ledger.Load"
    assert result["callees"][0]["file"] == "src/Engine.cs" and result["callees"][0]["line"] == 10


def test_include_permalinks_returns_them_on_every_node():
    result = _run(include_permalinks=True)
    assert result["callers"][0]["permalink"] == LINK
    assert result["callees"][0]["callees"][0]["permalink"] == LINK


def test_compact_answer_drops_the_four_node_permalinks():
    compact = len(json.dumps(_run()))
    full = len(json.dumps(_run(include_permalinks=True)))
    assert full - compact >= 4 * len(LINK)
