import warnings
warnings.filterwarnings(
    "ignore",
    message=r".*Field 'lifespan' has an incomplete definition.*",
)

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

mcp_server = FastMCP(
    "ContextHub",
    instructions="ContextHub: Universal Code & Knowledge RAG server providing hybrid search, AST code symbols, documentation retrieval, and repository indexing.",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)

from app.mcp.tools import register_mcp_tools_and_resources
from app.services.poller import start_poller_daemon, stop_poller_daemon

register_mcp_tools_and_resources(mcp_server)

