"""find_symbol requires `symbol` (the same name as trace_path) and still accepts the old `name` as an optional deprecated alias."""

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


def test_schema_requires_symbol_and_lists_name_as_optional_deprecated_alias():
    tools = _tools()
    schema = tools["find_symbol"].parameters
    props = schema["properties"]
    assert schema["required"] == ["symbol"]
    assert props["symbol"]["type"] == "string" and "anyOf" not in props["symbol"] and "default" not in props["symbol"]
    assert "name" in props and "name" not in schema["required"]
    assert "Deprecated alias" in props["name"]["description"]
    assert "symbol" in tools["trace_path"].parameters["required"]


def test_sdk_typings_show_symbol_required_and_name_optional():
    sdk = build_sdk_declarations([_tools()["find_symbol"]])
    block = sdk[sdk.index("find_symbol(args"):]
    block = block[:block.index("): Promise<")]
    assert "symbol: string;" in block
    assert "name?: string | null;" in block


def test_code_mode_calls_accept_symbol_and_name(local_source_db):  # noqa: F811
    by_symbol = asyncio.run(call_tool_from_script("find_symbol", {"symbol": "GetTool"}))
    by_name = asyncio.run(call_tool_from_script("find_symbol", {"name": "GetTool"}))
    assert by_symbol["total"] == 1 and by_name == by_symbol
    with pytest.raises(ScriptToolError, match="pass 'symbol'"):
        asyncio.run(call_tool_from_script("find_symbol", {}))
