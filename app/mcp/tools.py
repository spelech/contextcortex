"""
MCP Tools, Resources, Resource Templates, and Prompts Registration.
"""
import logging
from app.services.database import (
    get_db_connection,
    extract_host_from_url,
    get_adr,
    list_adrs,
    create_adr,
    update_adr,
    supersede_adr,
    upsert_adr,
)
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
    handle_repo_summary_resource,
    handle_repo_architecture_resource,
    handle_repo_files_resource,
    handle_repo_routes_resource,
    handle_repo_adrs_resource,
    handle_search_infrastructure_docs,
    handle_onboard_repository,
    handle_triage_error,
    handle_investigate_change_impact,
    handle_get_recent_changes,
    handle_get_architecture,
    handle_manage_adr,
    handle_manage_local_file,
    handle_what_is_ingested,
    handle_read_file,
    handle_summarize_file,
    handle_grep_code,
    handle_diagnose_issue,
)

logger = logging.getLogger("contextcortex.mcp")

_SUPPORTED_LANGS = "Python, TypeScript/JS/TSX, C#, COBOL, Go, Rust, Java, C/C++"

_TOOL_DEFINITIONS = [
    (
        "search_code",
        handle_search_code,
        f"Use for conceptual or hybrid semantic + BM25 code retrieval across {_SUPPORTED_LANGS}. "
        "Returns AST signatures, line spans, permalinks, and bounded snippets (max_snippet_chars 200..6000, default 2000). "
        "Paginate with top_k/limit (clamped 1..25, default 5) and offset (advance via next_offset when has_more is True).",
    ),
    (
        "search_docs",
        handle_search_docs,
        "Use for hybrid semantic + BM25 search across Markdown architecture docs, runbooks, ADRs, summaries, and extracted PDFs. "
        "Bounds snippets via max_snippet_chars (200..6000, default 2000). "
        "Paginate with top_k/limit (clamped 1..25, default 5) and offset (advance via next_offset when has_more is True).",
    ),
    (
        "find_symbol",
        handle_find_symbol,
        f"Use when you know an exact or partial symbol name (function, method, class, struct, interface, COBOL paragraph) across {_SUPPORTED_LANGS}. "
        "Avoids broad vector scans by querying the AST symbol table directly. "
        "Paginate with limit (clamped 1..100, default 30) and offset (returns total, has_more, next_offset).",
    ),
    (
        "trace_path",
        handle_trace_path,
        f"Use to traverse inbound callers, outbound callees, imports, inheritance, and cross-repo HTTP boundaries via BFS (depth 1..5) across {_SUPPORTED_LANGS}. "
        "Paginate with limit (clamped 1..200, default 50) and offset (returns total_callers, total_callees, has_more, next_offset).",
    ),
    (
        "find_routes",
        handle_find_routes,
        "Use to discover HTTP/API route endpoints and handler symbols across FastAPI, Flask, Django, Express/NestJS, ASP.NET Core, Go, Rust, and Java services. "
        "Paginate with limit (clamped 1..200, default 50) and offset (returns total, has_more, next_offset).",
    ),
    (
        "find_api_callers",
        handle_find_api_callers,
        "Use to find frontend and microservice HTTP client call sites invoking a target URL or route pattern across repositories. "
        "Paginate with limit (clamped 1..200, default 50) and offset (returns total, has_more, next_offset).",
    ),
    (
        "get_file_outline",
        handle_get_file_outline,
        f"Use before read_file to inspect a file's AST classes, functions, signatures, and line spans across {_SUPPORTED_LANGS} without loading full source text. "
        "Paginate large files with limit (clamped 1..500, default 150) and offset (returns total_symbols, has_more, next_offset).",
    ),
    (
        "list_repositories",
        handle_list_repositories,
        "Use to list all registered Git repositories and monitored local paths with active branches, commit SHAs, sync status, and file totals.",
    ),
    (
        "get_recent_changes",
        handle_get_recent_changes,
        f"Use to inspect retained Git commit history for a repository, optionally filtered by filepath or AST symbol ({_SUPPORTED_LANGS}). "
        "Caps files_changed per commit to 25 entries (files_changed_total, files_changed_truncated). "
        "Paginate with limit (clamped 1..50, default 10) and offset.",
    ),
    (
        "sync_repository",
        handle_sync_repository,
        "Use to trigger an asynchronous background Git fetch and delta re-indexing run for one repository or all registered sources (requires editor role).",
    ),
    (
        "index_status",
        handle_index_status,
        "Use to inspect global vector store health, point counts, active dense/sparse embedding models, and Git provider authentication status.",
    ),
    (
        "get_architecture",
        handle_get_architecture,
        f"Use first when onboarding onto a codebase: synthesizes language breakdown ({_SUPPORTED_LANGS}), manifests, entry points, modules, hub symbols, route counts, and active ADRs.",
    ),
    (
        "manage_adr",
        handle_manage_adr,
        "Use to list, search, get, create, update, or supersede Architecture Decision Records (ADRs). "
        "Paginate 'list' and 'search' actions with limit (clamped 1..100, default 25) and offset (returns total, has_more, next_offset).",
    ),
    (
        "manage_local_file",
        handle_manage_local_file,
        "Use to upload, replace, delete (editor role), read, or preview (viewer role) files in managed local storage with immediate AST and vector indexing.",
    ),
    (
        "what_is_ingested",
        handle_what_is_ingested,
        "Use to inspect ingested Git repositories, monitored local paths, and local storage inventory. "
        "When include_files=True or detail_level='detailed', paginates file lists via limit (clamped 1..500, default 100) and offset per source (total_files, has_more, next_offset).",
    ),
    (
        "read_file",
        handle_read_file,
        f"Use to read exact 1-based line slices (start_line..end_line) across {_SUPPORTED_LANGS}, Markdown, or configs from disk or vector chunk reconstruction. "
        "Returns total_lines, start_line, end_line, has_more, and next_start_line for sequential line-window pagination.",
    ),
    (
        "summarize_file",
        handle_summarize_file,
        "Use to fetch a cached executive summary or generate a fresh structured LLM summary (force_refresh=True) for a large source or documentation file.",
    ),
    (
        "grep_code",
        handle_grep_code,
        f"Use for exact literal or regex pattern matching across {_SUPPORTED_LANGS} and configs with context_lines (0..10) and AST symbol attribution. "
        "Truncates lines > 400 chars with '...[line truncated]'. Paginate with max_results/limit (clamped 1..100, default 30) and offset.",
    ),
    (
        "diagnose_issue",
        handle_diagnose_issue,
        f"Use for forensic triage of stack traces, error logs, or failing HTTP routes across {_SUPPORTED_LANGS}. "
        "Resolves stack frames (context_lines 1..15), error literals, API routes, and semantic candidates (limit 1..20).",
    ),
]

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
    """Register all 19 tools, compact catalog resource, 5 per-repo resource templates, and 5 prompts."""
    if server is None:
        from app.mcp.mcp_server import mcp_server
        server = mcp_server

    existing_tools = {t.name for t in server._tool_manager.list_tools()}
    for tool_name, handler_fn, description in _TOOL_DEFINITIONS:
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
            "Structured workflow to map a repository's architecture, entry points, API routes, and recent commits.",
            handle_onboard_repository,
        ),
        (
            "triage_error",
            "Forensic workflow to diagnose an error, stack trace, or failing endpoint down to root-cause lines and commits.",
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
