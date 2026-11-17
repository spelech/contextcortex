"""trace_path with an unknown class returns found: false and candidates, not the merged graph of every same-named method."""

import asyncio
import json

from app.mcp.handlers.symbol_handlers import handle_trace_path
from app.services.trace_target_lookup import MAX_CANDIDATES
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


def test_candidates_merge_copies_of_the_same_source(chain_db):  # noqa: F811
    """The same source indexed as many repos gives one candidate per symbol, file, and line, not one per copy."""
    from app.services.database import get_db_connection

    copies = [f"shop-copy-{i}" for i in range(MAX_CANDIDATES + 2)]
    with get_db_connection() as conn:
        for copy in copies:
            conn.execute(
                "INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language) "
                "VALUES (?, ?, 'GetByInstanceId', 'FakeToolReader.GetByInstanceId', 'method_declaration', 3, 3, '', 'c_sharp')",
                (copy, f"{copy}://Tests/FakeToolReader.cs"),
            )
        conn.commit()
    result = json.loads(asyncio.run(handle_trace_path(symbol="WrongReader.GetByInstanceId", direction="both", depth=2)))
    keys = [(c["symbol"], c["file"], c["line"]) for c in result["candidates"]]
    assert len(keys) == len(set(keys))
    assert {k[0] for k in keys} >= {"FakeToolReader.GetByInstanceId", "ToolReader.GetByInstanceId", "ToolService.GetByInstanceId"}
    fake = next(c for c in result["candidates"] if c["symbol"] == "FakeToolReader.GetByInstanceId")
    assert fake["file"] == "Tests/FakeToolReader.cs" and set(fake["repos"]) == {REPO, *copies}
