import warnings
warnings.filterwarnings(
    "ignore",
    message=r".*Field 'lifespan' has an incomplete definition.*",
)

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

MCP_SERVER_VERSION = "2.21.4"  # x-release-please-version

mcp_server = FastMCP(
    "ContextCortex",
    instructions="ContextCortex: Universal Code & Knowledge RAG server providing hybrid search, AST code symbols, documentation retrieval, and repository indexing.",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)
if hasattr(mcp_server, "_mcp_server"):
    mcp_server._mcp_server.version = MCP_SERVER_VERSION

from app.mcp.tools import register_mcp_tools_and_resources
from app.services.poller import start_poller_daemon, stop_poller_daemon

register_mcp_tools_and_resources(mcp_server)

