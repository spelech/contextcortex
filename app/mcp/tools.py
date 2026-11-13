"""
MCP Tools, Resources, Resource Templates, and Prompts Registration.
"""
import logging
import os
from typing import List, Tuple, Any

from app.services.database import get_db_connection
from app.services.search import execute_hybrid_search, trace_symbol_path
from app.services.indexing import get_dynamic_catalog_description, sync_single_git_repo, run_full_indexing
from app.services.vector_store import get_vector_store_config
from app.services.git_manager import format_git_permalink
from app.services.chunking import match_route_and_call, normalize_path_pattern

from app.mcp.handlers import (
    handle_search,
    handle_find_symbol,
    handle_trace_path,
    handle_find_implementation_symbol,
    handle_find_routes,
    handle_list_repositories,
    handle_manage,
    handle_catalog_summary,
    handle_repo_summary_resource,
    handle_repo_architecture_resource,
    handle_repo_files_resource,
    handle_repo_routes_resource,
    handle_repo_adrs_resource,
    handle_search_infrastructure_docs,
    handle_onboard_repository,
    handle_triage_error,
    handle_investigate_change_impact,
    handle_get_architecture,
    handle_read_file,
    handle_grep_code,
    handle_diagnose_issue,
    handle_execute_script,
    handle_code_mode_sdk_resource,
)

logger = logging.getLogger("contextcortex.mcp")

_SUPPORTED_LANGS = "Python, TypeScript/JS/TSX, C#, COBOL, Go, Rust, Java, C/C++"

_DEFAULT_TOOL_DEFINITIONS: List[Tuple[str, Any, str]] = [
    (
        "diagnose_issue",
        handle_diagnose_issue,
        f"Use for forensic triage of stack traces, error logs, or failing HTTP routes across {_SUPPORTED_LANGS}. "
        "Resolves stack frames (context_lines 1..15), error literals, API routes, and semantic candidates (limit 1..20).",
    ),
    (
        "execute_script",
        handle_execute_script,
        "Code Mode: use to chain several ContextCortex tool calls in ONE call. Send an async JavaScript body; it calls tools with "
        "`await tools.<tool>(args)` (results are parsed JSON, a tool error throws) and returns only what you need. "
        "Example: `const r = await tools.find_routes({query: 'publish', kind: 'handlers'}); const t = await tools.trace_path({symbol: r.routes[0].handler, "
        "direction: 'callees', depth: 3}); return t.callees.map(c => c.symbol);`. Typed signatures: resource contextcortex://code-mode/sdk.d.ts. "
        "Limits: 30 s, 50 tool calls, 64 MB (CODE_MODE_* settings). Returns {result, logs, executionTimeMs, toolCallsCount}.",
    ),
    (
        "find_routes",
        handle_find_routes,
        "Use to discover HTTP/API server route handlers (kind='handlers'), frontend/microservice client call sites (kind='callers'), or both (default kind='both') across FastAPI, Flask, Django, Express/NestJS, ASP.NET Core, Go, Rust, Java, and JS/TS clients. "
        "Paginate with limit (clamped 1..200, default 50) and offset (advance via next_offset when has_more is True).",
    ),
    (
        "find_symbol",
        handle_find_symbol,
        f"Use when you know an exact or partial symbol name (function, method, class, struct, interface, COBOL paragraph) across {_SUPPORTED_LANGS}. "
        "Avoids broad vector scans by querying the AST symbol table directly. "
        "Paginate with limit (clamped 1..100, default 30) and offset (returns total, has_more, next_offset).",
    ),
    (
        "get_architecture",
        handle_get_architecture,
        f"Use first when onboarding onto a codebase: synthesizes language breakdown ({_SUPPORTED_LANGS}), manifests, entry points, modules, hub symbols, route counts, and active ADRs.",
    ),
    (
        "grep_code",
        handle_grep_code,
        f"Use for exact literal or regex pattern matching across {_SUPPORTED_LANGS} and configs with context_lines (0..10) and AST symbol attribution. "
        "Truncates lines > 400 chars with '...[line truncated]'. Paginate with limit (clamped 1..100, default 30) and offset.",
    ),
    (
        "list_repositories",
        handle_list_repositories,
        "Use to list registered Git repositories, monitored local paths, and local storage inventory, optionally including paginated file lists (include_files=True, limit 1..500) or vector store/embedding/auth health status (include_status=True).",
    ),
    (
        "read_file",
        handle_read_file,
        f"Use to read exact 1-based line slices (start_line..end_line) across {_SUPPORTED_LANGS}, Markdown, or configs, or set outline_only=True to inspect AST classes/functions/signatures before slicing lines. "
        "Returns pagination cursors (next_start_line for text slices; total_symbols/has_more/next_offset for outline_only=True).",
    ),
    (
        "search",
        handle_search,
        f"Use for hybrid semantic + BM25 search across {_SUPPORTED_LANGS} code (scope='code'), Markdown specs/runbooks/ADRs/PDFs (scope='docs'), or both (default scope='all'). "
        "Bounds snippets via max_snippet_chars (200..6000, default 2000) and paginates via limit (1..25, default 5) and offset.",
    ),
    (
        "trace_path",
        handle_trace_path,
        f"Use to traverse inbound callers, outbound callees, imports, inheritance, and cross-repo HTTP boundaries via BFS (depth 1..5) across {_SUPPORTED_LANGS}. "
        "Paginate with limit (clamped 1..200, default 50) and offset (returns total_callers, total_callees, has_more, next_offset).",
    ),
]

_WRITE_TOOL_DEFINITIONS: List[Tuple[str, Any, str]] = [
    (
        "manage",
        handle_manage,
        "Admin/write tool to trigger repository synchronization (action='sync_repo') or upload, replace, delete (editor role), read, or preview (viewer role) managed local storage files with immediate AST and vector indexing.",
    ),
]

# Backward-compatible reference to default tool list
_TOOL_DEFINITIONS = _DEFAULT_TOOL_DEFINITIONS


def write_tools_enabled() -> bool:
    """Returns True when MCP_ENABLE_WRITE_TOOLS enables the gated `manage` tool."""
    return os.getenv("MCP_ENABLE_WRITE_TOOLS", "false").strip().lower() in ("1", "true", "yes", "on")


def get_tool_definitions() -> List[Tuple[str, Any, str]]:
    """Returns active MCP tool definitions (10 default read/search/code-mode tools, plus `manage` if enabled)."""
    if write_tools_enabled():
        return list(_DEFAULT_TOOL_DEFINITIONS) + list(_WRITE_TOOL_DEFINITIONS)
    return list(_DEFAULT_TOOL_DEFINITIONS)


_RESOURCE_TEMPLATE_DEFINITIONS = [
    (
        "knowledge://repo/{repo}/summary",
        "repo_summary",
        "Per-repository status, commit SHA, file count, language distribution, symbol/route/ADR counts, and sub-resource URIs.",
        handle_repo_summary_resource,
    ),
    (
        "knowledge://repo/{repo}/architecture",
        "repo_architecture_overview",
        "Synthesized architecture overview (languages, manifests, entry points, modules, hub symbols, routes, ADRs) for a repository.",
        handle_repo_architecture_resource,
    ),
    (
        "knowledge://repo/{repo}/files/{page}",
        "repo_files_page",
        "Paginated repository file inventory (100 files per 1-indexed page; includes total_files, total_pages, has_more, next_uri).",
        handle_repo_files_resource,
    ),
    (
        "knowledge://repo/{repo}/routes/{page}",
        "repo_routes_page",
        "Paginated repository HTTP/API routes (50 routes per 1-indexed page; includes total_routes, total_pages, has_more, next_uri).",
        handle_repo_routes_resource,
    ),
    (
        "knowledge://repo/{repo}/adrs",
        "repo_adrs",
        "Architecture Decision Records (ADRs) registered for the specified repository.",
        handle_repo_adrs_resource,
    ),
]


def register_mcp_tools_and_resources(server=None):
    """Register the consolidated 10-tool default MCP surface (11 when MCP_ENABLE_WRITE_TOOLS=true), resources, templates, and prompts."""
    if server is None:
        from app.mcp.mcp_server import mcp_server
        server = mcp_server

    existing_tools = {t.name for t in server._tool_manager.list_tools()}
    for tool_name, handler_fn, description in get_tool_definitions():
        if tool_name not in existing_tools:
            server.tool(name=tool_name, description=description)(handler_fn)

    existing_resources = {str(r.uri) for r in server._resource_manager.list_resources()}
    if "knowledge://catalog/summary" not in existing_resources:
        server.resource(
            "knowledge://catalog/summary",
            name="knowledge_catalog_summary",
            description="Compact catalog of indexed repositories, symbol totals, sample files, and granular per-repo resource template URIs.",
            mime_type="application/json",
        )(handle_catalog_summary)
    if "contextcortex://code-mode/sdk.d.ts" not in existing_resources:
        server.resource(
            "contextcortex://code-mode/sdk.d.ts",
            name="code_mode_sdk",
            description="TypeScript declarations of every tool that an execute_script (Code Mode) script can call, with argument docs.",
            mime_type="text/plain",
        )(handle_code_mode_sdk_resource)

    try:
        existing_templates = {str(t.uri_template) for t in server._resource_manager.list_templates()}
    except Exception:
        existing_templates = set()

    for uri_tpl, tpl_name, tpl_desc, tpl_fn in _RESOURCE_TEMPLATE_DEFINITIONS:
        if uri_tpl not in existing_templates:
            server.resource(
                uri_tpl,
                name=tpl_name,
                description=tpl_desc,
                mime_type="application/json",
            )(tpl_fn)

    existing_prompts = {p.name for p in server._prompt_manager.list_prompts()}
    prompt_defs = [
        (
            "search_infrastructure_docs",
            "Workflow to search system infrastructure documentation, ADRs, container mappings, or network routes.",
            handle_search_infrastructure_docs,
        ),
        (
            "find_implementation_symbol",
            "Workflow to locate functions, classes, and call graphs across registered codebases.",
            handle_find_implementation_symbol,
        ),
        (
            "onboard_repository",
            "Structured workflow to map a repository's architecture, entry points, API routes, and AST outlines.",
            handle_onboard_repository,
        ),
        (
            "triage_error",
            "Forensic workflow to diagnose an error, stack trace, or failing endpoint down to root-cause lines.",
            handle_triage_error,
        ),
        (
            "investigate_change_impact",
            "Blast-radius workflow to identify callers, cross-repo API consumers, and tests affected by changing a symbol.",
            handle_investigate_change_impact,
        ),
    ]
    for p_name, p_desc, p_fn in prompt_defs:
        if p_name not in existing_prompts:
            server.prompt(name=p_name, description=p_desc)(p_fn)

    return server
