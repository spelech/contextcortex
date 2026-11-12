import json
import logging
import sys
from typing import List, Dict, Any, Optional, Annotated, Callable
from pydantic import Field

from app.services.database import get_db_connection
from app.services.git_manager import format_git_permalink
from app.services.chunking import match_route_and_call
from app.services.chunking.route_specificity import (
    is_test_route_file as _is_test_route_file,
    most_specific_routes,
    route_key,
)

logger = logging.getLogger("contextcortex")


def _get_tools_attr(name, default):
    t_mod = sys.modules.get("app.mcp.tools")
    return getattr(t_mod, name, default) if t_mod else default


def _target_ownership(target_path: str, target_method: Optional[str], route_rows) -> Callable[[str, str], bool]:
    """
    Builds a check that tells if a client call belongs to the target path, or to a more specific known route.
    The target path is resolved to its own route(s) first: in each repository, the most specific route that matches
    it. A call that matches the target is then kept only when one of those routes is also the most specific route
    for the call in its repository (so `assistants/{id}` does not take the calls of `assistants/details`).
    When no known route matches the target, every matching call is kept.
    """
    routes = []
    for r in route_rows:
        rel_path = (r["filepath"].split("://", 1)[1] if "://" in r["filepath"] else r["filepath"]).replace("\\", "/")
        if not _is_test_route_file(rel_path):
            routes.append({"repo": r["repo"], "http_method": r["http_method"], "path_pattern": r["path_pattern"]})

    target_routes = most_specific_routes(target_path, target_method, routes)
    if not target_routes:
        return lambda _url, _method: True
    target_keys = {route_key(r) for r in target_routes}
    target_repos = {r["repo"] for r in target_routes}
    competing = [r for r in routes if r["repo"] in target_repos]

    def belongs(call_url: str, call_method: str) -> bool:
        owners = most_specific_routes(call_url, call_method or None, competing)
        return not owners or any(route_key(o) in target_keys for o in owners)

    return belongs


async def handle_find_routes(
    query: Annotated[Optional[str], Field(description="Optional route path or handler substring filter (e.g. '/api/v1/users' or 'checkout') across FastAPI, Flask, Django, Express/NestJS, ASP.NET Core, Go, Rust, and Spring controllers.")] = None,
    method: Annotated[Optional[str], Field(description="Optional HTTP verb filter (GET, POST, PUT, PATCH, DELETE).")] = None,
    repo: Annotated[Optional[str], Field(description="Optional repository name filter.")] = None,
    limit: Annotated[int, Field(description="Maximum API routes returned per page, clamped to 1..200 (default 50).")] = 50,
    offset: Annotated[int, Field(description="0-based route offset for pagination (default 0). Advance via next_offset when has_more is True.")] = 0,
) -> str:
    """List or search declared HTTP/API route endpoints across indexed repositories with bounded pagination."""
    try:
        from app.services.auth import enforce_tool_permission, Role, ForbiddenError
        enforce_tool_permission(Role.VIEWER)

        safe_limit = max(1, min(int(limit if limit is not None else 50), 200))
        safe_offset = max(0, int(offset if offset is not None else 0))

        with _get_tools_attr("get_db_connection", get_db_connection)() as conn:
            sql = (
                "SELECT r.id, r.repo, r.filepath, r.framework, r.http_method, r.path_pattern, "
                "r.handler_symbol, r.start_line, r.end_line, g.url as git_url, g.commit_sha, g.provider "
                "FROM api_routes r LEFT JOIN git_repositories g ON r.repo = g.name WHERE 1=1"
            )
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

            sql += " ORDER BY r.repo ASC, r.path_pattern ASC, r.http_method ASC, r.start_line ASC"
            rows = conn.execute(sql, params).fetchall()

        all_routes = []
        seen_routes = set()
        for r in rows:
            rel_path = (r["filepath"].split("://", 1)[1] if "://" in r["filepath"] else r["filepath"]).replace("\\", "/")
            if _is_test_route_file(rel_path):
                continue
            dedup_key = (r["repo"], r["http_method"], r["path_pattern"], rel_path, r["start_line"])
            if dedup_key in seen_routes:
                continue
            seen_routes.add(dedup_key)
            permalink = format_git_permalink(
                r["git_url"], r["commit_sha"], rel_path, r["start_line"], r["end_line"], provider=r["provider"]
            )
            all_routes.append({
                "repo": r["repo"],
                "method": r["http_method"],
                "path": r["path_pattern"],
                "framework": r["framework"],
                "handler": r["handler_symbol"],
                "file": rel_path,
                "lines": [r["start_line"], r["end_line"]],
                "permalink": permalink,
            })

        total = len(all_routes)
        paged_routes = all_routes[safe_offset : safe_offset + safe_limit]
        has_more = (safe_offset + safe_limit) < total
        next_offset = (safe_offset + safe_limit) if has_more else None

        return json.dumps({
            "query": (query or "").strip() or None,
            "method": method.strip().upper() if method and method.strip() else None,
            "repo": repo.strip() if repo and repo.strip() else None,
            "total": total,
            "offset": safe_offset,
            "limit": safe_limit,
            "has_more": has_more,
            "next_offset": next_offset,
            "routes": paged_routes,
        })
    except ForbiddenError as fe:
        logger.warning(f"Forbidden error in handle_find_routes: {fe}")
        return json.dumps({"error": f"Forbidden: {str(fe)}", "forbidden": True})
    except Exception as e:
        logger.error(f"find_routes failed: {e}")
        return json.dumps({"error": f"Error searching API routes: {str(e)}"})


async def handle_find_api_callers(
    path: Annotated[str, Field(description="Target HTTP endpoint path pattern or URL segment to match (e.g. '/api/v1/users/{id}' or '/auth/login') across TypeScript/JS/TSX, Python, C#, Go, Rust, and Java clients.")],
    method: Annotated[Optional[str], Field(description="Optional HTTP verb filter (GET, POST, PUT, PATCH, DELETE).")] = None,
    repo: Annotated[Optional[str], Field(description="Optional client repository name filter.")] = None,
    limit: Annotated[int, Field(description="Maximum client call sites returned per page, clamped to 1..200 (default 50).")] = 50,
    offset: Annotated[int, Field(description="0-based caller offset for pagination (default 0). Advance via next_offset when has_more is True.")] = 0,
) -> str:
    """Discover frontend and service HTTP client call sites invoking a target API route pattern with bounded pagination."""
    target_path = path.strip() if path else ""
    if not target_path:
        return json.dumps({"error": "endpoint path cannot be empty."})

    try:
        from app.services.auth import enforce_tool_permission, Role, ForbiddenError
        enforce_tool_permission(Role.VIEWER)

        safe_limit = max(1, min(int(limit if limit is not None else 50), 200))
        safe_offset = max(0, int(offset if offset is not None else 0))

        with _get_tools_attr("get_db_connection", get_db_connection)() as conn:
            sql = (
                "SELECT c.id, c.repo, c.filepath, c.http_method, c.url_pattern, c.caller_symbol, "
                "c.line_number, g.url as git_url, g.commit_sha, g.provider "
                "FROM api_client_calls c LEFT JOIN git_repositories g ON c.repo = g.name WHERE 1=1"
            )
            params: List[Any] = []

            if repo and repo.strip():
                sql += " AND c.repo = ?"
                params.append(repo.strip())

            sql += " ORDER BY c.repo ASC, c.filepath ASC, c.line_number ASC"
            rows = conn.execute(sql, params).fetchall()
            route_rows = conn.execute("SELECT repo, filepath, http_method, path_pattern FROM api_routes").fetchall()

        target_method_clean = method.strip().upper() if method and method.strip() else None
        belongs_to_target = _target_ownership(target_path, target_method_clean, route_rows)
        all_callers = []
        seen_callers = set()

        for c in rows:
            call_method = (c["http_method"] or "").upper()
            if target_method_clean and call_method and call_method != "ALL" and call_method != target_method_clean:
                continue

            if not match_route_and_call(target_path, c["url_pattern"]):
                continue
            if not belongs_to_target(c["url_pattern"], call_method):
                continue

            rel_path = (c["filepath"].split("://", 1)[1] if "://" in c["filepath"] else c["filepath"]).replace("\\", "/")
            dedup_key = (c["repo"], rel_path, c["http_method"], c["url_pattern"], c["caller_symbol"], c["line_number"])
            if dedup_key in seen_callers:
                continue
            seen_callers.add(dedup_key)

            permalink = format_git_permalink(
                c["git_url"], c["commit_sha"], rel_path, c["line_number"], c["line_number"], provider=c["provider"]
            )
            all_callers.append({
                "repo": c["repo"],
                "method": c["http_method"],
                "url": c["url_pattern"],
                "caller": c["caller_symbol"],
                "file": rel_path,
                "line": c["line_number"],
                "permalink": permalink,
            })

        total = len(all_callers)
        paged_callers = all_callers[safe_offset : safe_offset + safe_limit]
        has_more = (safe_offset + safe_limit) < total
        next_offset = (safe_offset + safe_limit) if has_more else None

        return json.dumps({
            "path": target_path,
            "method": target_method_clean,
            "total": total,
            "offset": safe_offset,
            "limit": safe_limit,
            "has_more": has_more,
            "next_offset": next_offset,
            "callers": paged_callers,
        })
    except ForbiddenError as fe:
        logger.warning(f"Forbidden error in handle_find_api_callers: {fe}")
        return json.dumps({"error": f"Forbidden: {str(fe)}", "forbidden": True})
    except Exception as e:
        logger.error(f"find_api_callers failed: {e}")
        return json.dumps({"error": f"Error searching API callers: {str(e)}"})
