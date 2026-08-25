import json
import logging
from typing import List, Dict, Any, Optional, Annotated
from pydantic import Field

from app.services.database import get_db_connection, extract_host_from_url, get_adr, list_adrs, create_adr, update_adr, supersede_adr, upsert_adr
from app.services.search import execute_hybrid_search, trace_symbol_path
from app.services.indexing import get_dynamic_catalog_description, sync_single_git_repo, run_full_indexing
from app.services.vector_store import get_vector_store_config
from app.services.git_manager import format_git_permalink
from app.services.chunking import match_route_and_call, normalize_path_pattern
from app.models.schemas import SearchRequest, FindSymbolRequest, GetFileOutlineRequest, SyncRequest

logger = logging.getLogger("contextcortex")
import sys

def _get_tools_attr(name, default):
    t_mod = sys.modules.get("app.mcp.tools")
    return getattr(t_mod, name, default) if t_mod else default


async def handle_find_routes(
    query: Annotated[Optional[str], Field(description="Path substring or pattern (e.g. '/api/v1/users' or 'checkout').")] = None,
    method: Annotated[Optional[str], Field(description="Filter by HTTP method (GET, POST, PUT, DELETE, etc.).")] = None,
    repo: Annotated[Optional[str], Field(description="Filter by repository name.")] = None,
    limit: Annotated[int, Field(description="Maximum routes to return (default 20).")] = 20
) -> str:
    """List or search API endpoints and HTTP route handlers across registered repositories."""
    try:
        with _get_tools_attr("get_db_connection", get_db_connection)() as conn:
            sql = "SELECT r.id, r.repo, r.filepath, r.framework, r.http_method, r.path_pattern, r.handler_symbol, r.start_line, r.end_line, g.url as git_url, g.commit_sha, g.provider FROM api_routes r LEFT JOIN git_repositories g ON r.repo = g.name WHERE 1=1"
            params: List[Any] = []

            if query and query.strip():
                clean_q = query.strip()
                sql += " AND (r.path_pattern LIKE ? OR r.handler_symbol LIKE ?)"
                params.extend([f"%{clean_q}%", f"%{clean_q}%"])

            if method and method.strip():
                sql += " AND (UPPER(r.http_method) = ? OR UPPER(r.http_method) = 'ALL')"
                params.append(method.strip().upper())

            if repo and repo.strip():
                sql += " AND r.repo = ?"
                params.append(repo.strip())

            sql += f" ORDER BY r.repo ASC, r.path_pattern ASC LIMIT {limit}"
            rows = conn.execute(sql, params).fetchall()

        if not rows:
            return f"No API routes found matching query: '{query or ''}'."

        lines = [f"Found {len(rows)} matching API endpoints:\n"]
        for r in rows:
            rel_path = r["filepath"].split("://", 1)[1] if "://" in r["filepath"] else r["filepath"]
            permalink = format_git_permalink(r["git_url"], r["commit_sha"], rel_path, r["start_line"], r["end_line"], provider=r["provider"])
            handler_str = f" Handler: `{r['handler_symbol']}`" if r["handler_symbol"] else ""
            lines.append(
                f"- **[{r['http_method']}] `{r['path_pattern']}`** ({r['framework']}) in `[{r['repo']}] {rel_path}` (Lines {r['start_line']}-{r['end_line']}){handler_str}\n"
                f"  Permalink: {permalink}"
            )

        return "\n".join(lines)
    except Exception as e:
        logger.error(f"find_routes failed: {e}")
        return f"Error searching API routes: {str(e)}"


async def handle_find_api_callers(
    path: Annotated[str, Field(description="Endpoint path pattern or URL segment to match (e.g. '/users/{id}' or '/auth/login').")],
    method: Annotated[Optional[str], Field(description="Target HTTP method (GET, POST, etc.).")] = None,
    repo: Annotated[Optional[str], Field(description="Filter client search by repository.")] = None
) -> str:
    """Find client call sites and services that invoke a specific API endpoint or URL pattern."""
    target_path = path.strip() if path else ""
    if not target_path:
        return "Error: endpoint path cannot be empty."

    try:
        with _get_tools_attr("get_db_connection", get_db_connection)() as conn:
            sql = "SELECT c.id, c.repo, c.filepath, c.http_method, c.url_pattern, c.caller_symbol, c.line_number, g.url as git_url, g.commit_sha, g.provider FROM api_client_calls c LEFT JOIN git_repositories g ON c.repo = g.name WHERE 1=1"
            params: List[Any] = []

            if repo and repo.strip():
                sql += " AND c.repo = ?"
                params.append(repo.strip())

            rows = conn.execute(sql, params).fetchall()

        matching_calls = []
        target_method_clean = method.strip().upper() if method and method.strip() else None

        for r in rows:
            call_method = (r["http_method"] or "").upper()
            if target_method_clean and call_method and call_method != "ALL" and call_method != target_method_clean:
                continue

            if match_route_and_call(target_path, r["url_pattern"]):
                matching_calls.append(r)

        if not matching_calls:
            return f"No client call sites found invoking endpoint pattern: '{target_path}'."

        lines = [f"Found {len(matching_calls)} call sites invoking endpoint `{target_path}`:\n"]
        for c in matching_calls:
            rel_path = c["filepath"].split("://", 1)[1] if "://" in c["filepath"] else c["filepath"]
            permalink = format_git_permalink(c["git_url"], c["commit_sha"], rel_path, c["line_number"], c["line_number"], provider=c["provider"])
            caller_str = f" Caller: `{c['caller_symbol']}`" if c["caller_symbol"] else ""
            method_str = f"[{c['http_method']}] " if c["http_method"] else ""
            lines.append(
                f"- **{method_str}`{c['url_pattern']}`** in `[{c['repo']}] {rel_path}` (Line {c['line_number']}){caller_str}\n"
                f"  Permalink: {permalink}"
            )

        return "\n".join(lines)
    except Exception as e:
        logger.error(f"find_api_callers failed: {e}")
        return f"Error searching API callers: {str(e)}"


