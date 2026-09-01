"""
MCP Tools and Resources Registration
"""
import logging
from typing import Optional, List, Dict, Any
from app.services.database import get_db_connection, extract_host_from_url, get_adr, list_adrs, create_adr, update_adr, supersede_adr, upsert_adr
from app.services.search import execute_hybrid_search, trace_symbol_path
from app.services.indexing import get_dynamic_catalog_description, sync_single_git_repo, run_full_indexing
from app.services.vector_store import get_vector_store_config
from app.services.git_manager import format_git_permalink
from app.services.chunking import match_route_and_call, normalize_path_pattern

from app.mcp.handlers import (
    handle_search_code,
    handle_search_docs,
    handle_find_symbol,
    handle_trace_path,
    handle_get_file_outline,
    handle_find_implementation_symbol,
    handle_find_routes,
    handle_find_api_callers,
    handle_list_repositories,
    handle_sync_repository,
    handle_index_status,
    handle_catalog_summary,
    handle_search_infrastructure_docs,
    handle_get_architecture,
    handle_manage_adr,
    handle_manage_local_file,
    handle_what_is_ingested,
)

logger = logging.getLogger("contextcortex.mcp")

def register_mcp_tools_and_resources(server=None):
    """Register all 7 tools, resources, and prompts onto the FastMCP server instance."""
    if server is None:
        from app.mcp.mcp_server import mcp_server
        server = mcp_server

    existing_tools = {t.name for t in server._tool_manager.list_tools()}

    if "search_code" not in existing_tools:
        server.tool(
            name="search_code",
            description="Hybrid semantic and BM25 search over code functions, classes, and logic snippets with line numbers and GitHub links."
        )(handle_search_code)

    if "search_docs" not in existing_tools:
        server.tool(
            name="search_docs",
            description="Hybrid search across system documentation, markdown notes, architectural decisions, and runbooks."
        )(handle_search_docs)

    if "find_symbol" not in existing_tools:
        server.tool(
            name="find_symbol",
            description="Instant exact or prefix symbol lookup (functions, classes, structs, interfaces) from AST index without broad token scans."
        )(handle_find_symbol)

    if "trace_path" not in existing_tools:
        server.tool(
            name="trace_path",
            description="Deterministically traverse function call graphs, module imports, and inheritance hierarchies using AST relationships (BFS)."
        )(handle_trace_path)

    if "find_routes" not in existing_tools:
        server.tool(
            name="find_routes",
            description="List or search API endpoints and HTTP route handlers across registered repositories."
        )(handle_find_routes)

    if "find_api_callers" not in existing_tools:
        server.tool(
            name="find_api_callers",
            description="Find client call sites and services that invoke a specific API endpoint or URL pattern."
        )(handle_find_api_callers)

    if "get_file_outline" not in existing_tools:
        server.tool(
            name="get_file_outline",
            description="Get the AST outline (classes, methods, functions, line numbers) of a file without retrieving its entire token body."
        )(handle_get_file_outline)

    if "list_repositories" not in existing_tools:
        server.tool(
            name="list_repositories",
            description="Lists all indexed local paths and remote Git repositories, including active branches, commit SHAs, and file counts."
        )(handle_list_repositories)

    if "sync_repository" not in existing_tools:
        server.tool(
            name="sync_repository",
            description="Trigger an immediate re-fetch and re-indexing of a registered Git repo or local path."
        )(handle_sync_repository)

    if "index_status" not in existing_tools:
        server.tool(
            name="index_status",
            description="Get global index health, vector counts, Git provider auth sources, and active embedding models."
        )(handle_index_status)

    if "get_architecture" not in existing_tools:
        server.tool(
            name="get_architecture",
            description="Synthesizes language distributions, key entry points, primary framework modules, route counts, and active ADRs into a concise summary."
        )(handle_get_architecture)

    if "manage_adr" not in existing_tools:
        server.tool(
            name="manage_adr",
            description="Manage Architecture Decision Records (ADRs): read, create, update, supersede, or search records across repositories."
        )(handle_manage_adr)

    if "manage_local_file" not in existing_tools:
        server.tool(
            name="manage_local_file",
            description="Manage files in ContextCortex local storage: upload, replace, read, or delete files with immediate vector indexing."
        )(handle_manage_local_file)

    if "what_is_ingested" not in existing_tools:
        server.tool(
            name="what_is_ingested",
            description="Inspect all ingested Git repositories, monitored local paths, and uploaded local storage files with optional filtering and detailed file trees."
        )(handle_what_is_ingested)

    existing_resources = {str(r.uri) for r in server._resource_manager.list_resources()}
    if "knowledge://catalog/summary" not in existing_resources:
        server.resource(
            "knowledge://catalog/summary",
            name="knowledge_catalog_summary",
            description="Catalog of indexed repositories, documentation files, and AST symbol distributions.",
            mime_type="text/markdown"
        )(handle_catalog_summary)

    existing_prompts = {p.name for p in server._prompt_manager.list_prompts()}
    if "search_infrastructure_docs" not in existing_prompts:
        server.prompt(
            name="search_infrastructure_docs",
            description="Workflow to search system infrastructure documentation, container mappings, or network routes."
        )(handle_search_infrastructure_docs)

    if "find_implementation_symbol" not in existing_prompts:
        server.prompt(
            name="find_implementation_symbol",
            description="Workflow to locate functions, classes, and logic across registered codebases."
        )(handle_find_implementation_symbol)

    return server

