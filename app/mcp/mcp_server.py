import warnings
warnings.filterwarnings(
    "ignore",
    message=r".*Field 'lifespan' has an incomplete definition.*",
)

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

MCP_SERVER_VERSION = "2.27.4"  # x-release-please-version

MCP_SERVER_INSTRUCTIONS = (
    "ContextCortex: code and documentation search across indexed repositories "
    "(AST symbols, call graphs, HTTP routes, hybrid search).\n"
    "Select the first tool for the task:\n"
    "- Bug report, stack trace, error log, or failing HTTP route: diagnose_issue. "
    "One call gives the call chain from the route or frame to the likely fault, "
    "with call-site lines and evidence. Then use read_file only for the lines "
    "that you must confirm.\n"
    "- Known symbol name: find_symbol. Exact text or regex: grep_code. "
    "Concept or documentation: search.\n"
    "- Callers or callees of a known symbol: trace_path. "
    "HTTP handlers and client calls: find_routes.\n"
    "- New codebase: get_architecture. Repository names: list_repositories.\n"
    "- Several lookups in one round trip: execute_script.\n"
    "Pass repo=<name> when you know the repository."
)

mcp_server = FastMCP(
    "ContextCortex",
    instructions=MCP_SERVER_INSTRUCTIONS,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)
if hasattr(mcp_server, "_mcp_server"):
    mcp_server._mcp_server.version = MCP_SERVER_VERSION

from app.mcp.tools import register_mcp_tools_and_resources
from app.services.poller import start_poller_daemon, stop_poller_daemon

register_mcp_tools_and_resources(mcp_server)

