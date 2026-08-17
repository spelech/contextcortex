from mcp.server import Server
from mcp.server.sse import SseServerTransport
from typing import List, Dict, Any, Optional
from mcp.types import (
    Tool, TextContent, Resource, Prompt, PromptMessage, PromptArgument,
    ListToolsResult, CallToolResult, ListResourcesResult, ReadResourceResult,
    ListPromptsResult, GetPromptResult,
    CallToolRequestParams, ReadResourceRequestParams, GetPromptRequestParams
)

from app.mcp.tools import get_tools, execute_tool, get_resources, read_resource, get_prompts, get_prompt

mcp_server = Server("notes-rag-mcp")
sse_transport = SseServerTransport("/messages/")

@mcp_server.list_tools()
async def list_tools_handler() -> List[Tool]:
    return await get_tools()

@mcp_server.call_tool()
async def call_tool_handler(name: str, arguments: dict) -> List[TextContent]:
    return await execute_tool(name, arguments)

@mcp_server.list_resources()
async def list_resources_handler() -> List[Resource]:
    return await get_resources()

@mcp_server.read_resource()
async def read_resource_handler(uri) -> str:
    return await read_resource(str(uri))

@mcp_server.list_prompts()
async def list_prompts_handler() -> List[Prompt]:
    return await get_prompts()

@mcp_server.get_prompt()
async def get_prompt_handler(name: str, arguments: Optional[Dict[str, Any]] = None) -> GetPromptResult:
    messages = await get_prompt(name, arguments or {})
    return GetPromptResult(description="Prompt Result", messages=messages)

