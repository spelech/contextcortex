from mcp.server import Server
from mcp.server.sse import SseServerTransport
from typing import List, Dict, Any
from mcp.types import (
    Tool, TextContent, Resource, Prompt, PromptMessage, PromptArgument,
    ListToolsResult, CallToolResult, ListResourcesResult, ReadResourceResult,
    ListPromptsResult, GetPromptResult,
    CallToolRequestParams, ReadResourceRequestParams, GetPromptRequestParams
)

from app.mcp.tools import get_tools, execute_tool, get_resources, read_resource, get_prompts, get_prompt

mcp_server = Server("notes-rag-mcp")
sse_transport = SseServerTransport("/messages/")

async def list_tools_handler(ctx, req) -> ListToolsResult:
    tools = await get_tools()
    return ListToolsResult(tools=tools)

async def call_tool_handler(ctx, req: CallToolRequestParams) -> CallToolResult:
    content = await execute_tool(req.name, req.arguments)
    return CallToolResult(content=content)

async def list_resources_handler(ctx, req) -> ListResourcesResult:
    resources = await get_resources()
    return ListResourcesResult(resources=resources)

async def read_resource_handler(ctx, req: ReadResourceRequestParams) -> ReadResourceResult:
    content = await read_resource(req.uri)
    return ReadResourceResult(contents=[TextContent(type="text", text=content)])

async def list_prompts_handler(ctx, req) -> ListPromptsResult:
    prompts = await get_prompts()
    return ListPromptsResult(prompts=prompts)

async def get_prompt_handler(ctx, req: GetPromptRequestParams) -> GetPromptResult:
    messages = await get_prompt(req.name, req.arguments)
    return GetPromptResult(description="Prompt Result", messages=messages)

mcp_server.add_request_handler("tools/list", dict, list_tools_handler)
mcp_server.add_request_handler("tools/call", CallToolRequestParams, call_tool_handler)
mcp_server.add_request_handler("resources/list", dict, list_resources_handler)
mcp_server.add_request_handler("resources/read", ReadResourceRequestParams, read_resource_handler)
mcp_server.add_request_handler("prompts/list", dict, list_prompts_handler)
mcp_server.add_request_handler("prompts/get", GetPromptRequestParams, get_prompt_handler)
