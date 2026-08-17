from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

mcp_server = FastMCP(
    "knowledge-rag-mcp",
    instructions="Hybrid search, AST code symbols, documentation retrieval and repository indexing server.",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)

from app.mcp.tools import register_mcp_tools_and_resources

register_mcp_tools_and_resources(mcp_server)
