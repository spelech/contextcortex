"""The Code Mode result types (sdk.d.ts) agree with what the tools really return to a script."""

import asyncio
import re
from types import SimpleNamespace
from unittest.mock import patch

from app.mcp.handlers.script_handlers import call_tool_from_script
from app.services.database import get_db_connection
from app.services.script_sdk_types import _RESULT_TYPE_NAMES, RESULT_INTERFACES, build_sdk_declarations
from tests.test_diagnose_evidence_chain import REPO, chain_db  # noqa: F401  (pytest fixture)
from tests.test_diagnose_working_path import WORKING_ISSUE, _add_assistant_path


def _refs(ts: str):
    """The declared interfaces that a TypeScript type refers to, for example ChainStep in 'ChainStep[]'."""
    return [name for name in re.findall(r"[A-Za-z]+", ts) if name in RESULT_INTERFACES]


def _check(value, iface, where, seen):
    """Every real field is declared, every required field is there, and nested interfaces agree too."""
    assert isinstance(value, dict), f"{where}: {iface} is not an object"
    declared = {key.rstrip("?"): (ts, not key.endswith("?")) for key, ts in RESULT_INTERFACES[iface].items()}
    extra = sorted(set(value) - set(declared))
    assert not extra, f"{where}: {iface} does not declare {extra}"
    missing = sorted(key for key, (_ts, required) in declared.items() if required and key not in value)
    assert not missing, f"{where}: {iface} declares {missing}, but the result does not have them"
    seen.add(iface)
    for key, (ts, _required) in declared.items():
        if value.get(key) is None:
            continue
        for ref in _refs(ts):
            items = value[key] if isinstance(value[key], list) else [value[key]]
            for index, item in enumerate(items):
                _check(item, ref, f"{where}.{key}[{index}]", seen)


def _call(tool, **tool_args):
    return asyncio.run(call_tool_from_script(tool, tool_args))


def _fake_search(**_kwargs):
    payload = {"repo": REPO, "rel_path": "Services/ToolService.cs", "start_line": 3, "end_line": 12,
               "full_symbol": "ToolService.PublishInstance", "kind": "method_declaration", "language": "c_sharp",
               "content": "public async Task<ToolDTO> PublishInstance(Guid id)"}
    return [SimpleNamespace(payload=payload, score=0.9, dense_score=0.8, sparse_score=0.4)]


def test_result_types_agree_with_real_tool_results(chain_db):  # noqa: F811
    _add_assistant_path(chain_db)
    with get_db_connection() as conn:
        conn.execute("INSERT INTO api_client_calls (repo, filepath, http_method, url_pattern, caller_symbol, line_number) "
                     "VALUES (?, ?, 'POST', '/api/v2/tools/{id}/publish', 'publishTool', 4)",
                     (REPO, str(chain_db / "client/api.ts")))
        conn.commit()
    seen = set()
    with patch("app.services.diagnostics.execute_hybrid_search", return_value=[]):
        for detail in (False, True):
            result = _call("diagnose_issue", issue_text=WORKING_ISSUE, repo=REPO, detail=detail)
            _check(result, "DiagnoseResult", "diagnose_issue", seen)
        assert result["call_chain"]["steps"] and result["working_path_comparison"]["steps"]
    for kind in ("both", "handlers", "callers"):
        _check(_call("find_routes", query="publish", kind=kind, repo=REPO), "FindRoutesResult", f"find_routes({kind})", seen)
    for permalinks in (False, True):
        trace = _call("trace_path", symbol="ToolService.PublishInstance", repo=REPO, depth=3, include_permalinks=permalinks)
        _check(trace, "TracePathResult", "trace_path", seen)
    assert trace["callees"] and trace["callers"]
    _check(_call("trace_path", symbol="Nope.Missing", repo=REPO), "TracePathResult", "trace_path(missing)", seen)
    _check(_call("find_symbol", symbol="GetByInstanceId", repo=REPO, exact=False), "FindSymbolResult", "find_symbol", seen)
    with patch("app.mcp.tools.execute_hybrid_search", _fake_search):
        _check(_call("search", query="publish", repo=REPO), "SearchResult", "search", seen)
    assert seen == set(RESULT_INTERFACES), f"not checked: {sorted(set(RESULT_INTERFACES) - seen)}"


def test_sdk_declares_the_result_types_of_the_main_tools():
    tools = [SimpleNamespace(name=name, description="", parameters={}) for name in _RESULT_TYPE_NAMES]
    sdk = build_sdk_declarations(tools)
    for name, result_type in _RESULT_TYPE_NAMES.items():
        assert f"  {name}(args?: {{\n  }}): Promise<{result_type}>;" in sdk
    for iface in RESULT_INTERFACES:
        assert f"interface {iface} {{ " in sdk
    assert "interface ChainStep { symbol: string; kind: string | null; file: string; lines: [number, number]; " in sdk
    assert "/** file/line is the call site in the caller; defined_at (path:line) is where the callee is defined. */" in sdk
