"""The server instructions and tool descriptions send bug reports to diagnose_issue.

MCP clients can defer tool schemas, so an agent sees only tool names and the server
instructions before it loads a tool. These checks keep the routing guidance visible there.
"""
from app.mcp.mcp_server import MCP_SERVER_INSTRUCTIONS, mcp_server
from app.mcp.tools import _DEFAULT_TOOL_DEFINITIONS


def _descriptions():
    return {name: description for name, _handler, description in _DEFAULT_TOOL_DEFINITIONS}


def test_server_publishes_routing_instructions():
    assert mcp_server.instructions == MCP_SERVER_INSTRUCTIONS


def test_instructions_name_every_default_tool():
    for name in _descriptions():
        assert name in MCP_SERVER_INSTRUCTIONS, f"instructions do not name {name}"


def test_routing_list_starts_with_diagnose_issue_for_bug_reports():
    bullets = [line for line in MCP_SERVER_INSTRUCTIONS.splitlines() if line.startswith("- ")]
    assert bullets, "instructions have no routing list"
    first = bullets[0].lower()
    assert "bug report" in first
    assert "stack trace" in first
    assert "diagnose_issue" in first


def test_lookup_tool_descriptions_point_to_diagnose_issue():
    descriptions = _descriptions()
    for name in ("find_routes", "trace_path", "find_symbol"):
        assert "diagnose_issue" in descriptions[name], f"{name} description does not name diagnose_issue"
