"""find_symbol takes `symbol` (the same name as trace_path) and still accepts the old `name` as a hidden alias."""

import asyncio
import json

import pytest
from mcp.server.fastmcp import FastMCP

from app.mcp.handlers.script_handlers import call_tool_from_script
from app.mcp.handlers.symbol_handlers import handle_find_symbol
from app.mcp.tools import register_mcp_tools_and_resources
from app.services.script_sandbox import ScriptToolError
from app.services.script_sdk_types import build_sdk_declarations
from tests.test_local_source_relative_paths import CONTROLLER, local_source_db  # noqa: F401  (pytest fixture)


def _run(coro):
    return json.loads(asyncio.run(coro))


def _tools():
    server = FastMCP("SymbolParameter")
    register_mcp_tools_and_resources(server)
    return {tool.name: tool for tool in server._tool_manager.list_tools()}


def test_find_symbol_accepts_symbol_and_the_name_alias(local_source_db):  # noqa: F811
    by_symbol = _run(handle_find_symbol(symbol="GetTool"))
    by_name = _run(handle_find_symbol(name="GetTool"))
    assert [s["file"] for s in by_symbol["symbols"]] == [CONTROLLER]
    assert by_name == by_symbol
    both = _run(handle_find_symbol(symbol="GetTool", name="NoSuchSymbol"))
    assert both["query"] == "GetTool" and both["total"] == 1


def test_mcp_call_accepts_the_name_alias_without_a_validation_error(local_source_db):  # noqa: F811
    server = FastMCP("SymbolParameterCall")
    register_mcp_tools_and_resources(server)
    for args in ({"symbol": "GetTool"}, {"name": "GetTool"}):
        content = asyncio.run(server.call_tool("find_symbol", args))
        blocks = content[0] if isinstance(content, tuple) else content
        assert json.loads(blocks[0].text)["total"] == 1, args


@pytest.mark.parametrize("kwargs", [{}, {"symbol": "  "}, {"name": ""}, {"symbol": None, "name": None}])
def test_find_symbol_without_a_symbol_gives_a_clear_error(kwargs):
    result = _run(handle_find_symbol(**kwargs))
    assert "'symbol'" in result["error"] and "'name'" in result["error"]


def test_schema_documents_symbol_only_and_matches_trace_path():
    tools = _tools()
    find_props = tools["find_symbol"].parameters["properties"]
    assert "symbol" in find_props and "name" not in find_props
    assert "alias" in find_props["symbol"]["description"]
    assert "symbol" in tools["trace_path"].parameters["properties"]
    for tool in tools.values():
        assert "name" not in tool.parameters.get("properties", {}), tool.name


def test_sdk_typings_show_symbol_for_find_symbol():
    sdk = build_sdk_declarations([_tools()["find_symbol"]])
    block = sdk[sdk.index("find_symbol(args"):]
    block = block[:block.index("Promise<any>;")]
    assert "symbol?: string | null;" in block
    assert "name?:" not in block and "name:" not in block


def test_code_mode_calls_accept_symbol_and_name(local_source_db):  # noqa: F811
    by_symbol = asyncio.run(call_tool_from_script("find_symbol", {"symbol": "GetTool"}))
    by_name = asyncio.run(call_tool_from_script("find_symbol", {"name": "GetTool"}))
    assert by_symbol["total"] == 1 and by_name == by_symbol
    with pytest.raises(ScriptToolError, match="pass 'symbol'"):
        asyncio.run(call_tool_from_script("find_symbol", {}))
