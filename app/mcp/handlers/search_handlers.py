import json
import logging
from typing import List, Dict, Any, Optional, Annotated
from pydantic import Field

from app.services.db import get_db_connection, extract_host_from_url, get_adr, list_adrs, create_adr, update_adr, supersede_adr, upsert_adr
from app.services.search import execute_hybrid_search, trace_symbol_path
from app.services.indexer import get_dynamic_catalog_description, sync_single_git_repo, run_full_indexing
from app.services.vector_store import get_vector_store_config
from app.services.git_manager import format_git_permalink
from app.services.chunker import match_route_and_call, normalize_path_pattern
from app.models.schemas import SearchRequest, FindSymbolRequest, GetFileOutlineRequest, SyncRequest

logger = logging.getLogger("contextcortex")
import sys

def _get_tools_attr(name, default):
    t_mod = sys.modules.get("app.mcp.tools")
    return getattr(t_mod, name, default) if t_mod else default


async def handle_search_code(
    query: Annotated[str, Field(description="Natural language question or code concept (e.g. 'JWT token authentication handler').")],
    repo: Annotated[Optional[str], Field(description="Optional repository name/alias to filter by.")] = None,
    language: Annotated[Optional[str], Field(description="Optional language filter (e.g. 'python', 'typescript', 'go').")] = None,
    limit: Annotated[int, Field(description="Max number of code blocks to return (default 5).")] = 5
) -> str:
    """Hybrid semantic and BM25 search over code functions, classes, and logic snippets with line numbers and GitHub links."""
    query = query.strip() if query else ""
    if not query:
        return "Error: search query cannot be empty."

    try:
        hits = _get_tools_attr("execute_hybrid_search", execute_hybrid_search)(query_text=query, doc_type="code", repo=repo, language=language, limit=limit)
        if not hits:
            return f"No matching code snippets found for query: '{query}'."

        formatted = []
        for hit in hits:
            p = hit.payload
            header = f"### [{p.get('repo')}] {p.get('rel_path')} (Lines {p.get('start_line')}-{p.get('end_line')})"
            if p.get("symbol"):
                header += f" - Symbol: `{p.get('symbol')}`"
            link_url = p.get("permalink_url") or p.get("github_url")
            if link_url:
                header += f"\nSource Link: {link_url}"
            header += f"\nRRF Score: {hit.score:.4f}\n"

            lang = p.get("language", "")
            block = f"{header}```{lang}\n{p.get('content')}\n```"
            formatted.append(block)

        return "\n\n========================\n\n".join(formatted)
    except Exception as e:
        logger.error(f"search_code failed: {e}")
        return f"Error executing code search: {str(e)}"


async def handle_search_docs(
    query: Annotated[str, Field(description="Search query or documentation topic.")],
    repo: Annotated[Optional[str], Field(description="Optional repository/vault filter.")] = None,
    category: Annotated[Optional[str], Field(description="Optional category filter.")] = None,
    tag: Annotated[Optional[str], Field(description="Optional tag filter.")] = None,
    limit: Annotated[int, Field(description="Max documents to return (default 5).")] = 5
) -> str:
    """Hybrid search across system documentation, markdown notes, architectural decisions, and runbooks."""
    query = query.strip() if query else ""
    if not query:
        return "Error: search query cannot be empty."

    try:
        hits = _get_tools_attr("execute_hybrid_search", execute_hybrid_search)(query_text=query, doc_type="doc", repo=repo, category=category, tag=tag, limit=limit)
        if not hits:
            return f"No matching documentation found for query: '{query}'."

        formatted = []
        for hit in hits:
            p = hit.payload
            tags_str = ", ".join(p.get("tags", []))
            header = f"### [{p.get('repo')}] {p.get('rel_path')}"
            if p.get("heading") and p.get("heading") != "Root":
                header += f" -> {p.get('heading')}"
            if tags_str:
                header += f"\nTags: {tags_str}"
            link_url = p.get("permalink_url") or p.get("github_url")
            if link_url:
                header += f"\nSource Link: {link_url}"
            header += f"\nRRF Score: {hit.score:.4f}\n"

            block = f"{header}---\n{p.get('content')}"
            formatted.append(block)


        return "\n\n========================\n\n".join(formatted)
    except Exception as e:
        logger.error(f"search_docs failed: {e}")
        return f"Error executing doc search: {str(e)}"


