import json
import logging
import sys
from typing import List, Dict, Any, Optional, Annotated, Callable, Literal
from pydantic import Field

from app.services.database import get_db_connection
from app.services.git_manager import format_git_permalink
from app.services.chunking import match_route_and_call
from app.services.chunking.route_specificity import (
    is_test_route_file as _is_test_route_file,
    most_specific_routes,
    route_key,
)
from app.services.source_paths import LocalSourceRoots

logger = logging.getLogger("contextcortex")


def _get_tools_attr(name, default):
    t_mod = sys.modules.get("app.mcp.tools")
    return getattr(t_mod, name, default) if t_mod else default


def _target_ownership(target_path: str, target_method: Optional[str], route_rows) -> Callable[[str, str], bool]:
    """
    Builds a check that tells if a client call belongs to the target path, or to a more specific known route.
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


def _query_route_handlers(conn, local_roots: LocalSourceRoots, clean_q: Optional[str], method_clean: Optional[str], repo_clean: Optional[str]) -> List[Dict[str, Any]]:
    sql = (
        "SELECT r.id, r.repo, r.filepath, r.framework, r.http_method, r.path_pattern, "
        "r.handler_symbol, r.start_line, r.end_line, g.url as git_url, g.commit_sha, g.provider "
        "FROM api_routes r LEFT JOIN git_repositories g ON r.repo = g.name WHERE 1=1"
    )
    params: List[Any] = []
    if clean_q:
        sql += " AND (r.path_pattern LIKE ? OR r.handler_symbol LIKE ?)"
        params.extend([f"%{clean_q}%", f"%{clean_q}%"])
    if method_clean:
        sql += " AND (UPPER(r.http_method) = ? OR UPPER(r.http_method) = 'ALL')"
        params.append(method_clean)
    if repo_clean:
        sql += " AND r.repo = ?"
        params.append(repo_clean)
    sql += " ORDER BY r.repo ASC, r.path_pattern ASC, r.http_method ASC, r.start_line ASC"
    rows = conn.execute(sql, params).fetchall()

    all_routes: List[Dict[str, Any]] = []
    seen_routes = set()
    for r in rows:
        rel_path = local_roots.relative(r["filepath"], r["repo"])
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
    return all_routes


def _query_route_callers(conn, local_roots: LocalSourceRoots, clean_q: Optional[str], method_clean: Optional[str], repo_clean: Optional[str]) -> List[Dict[str, Any]]:
    sql = (
        "SELECT c.id, c.repo, c.filepath, c.http_method, c.url_pattern, c.caller_symbol, "
        "c.line_number, g.url as git_url, g.commit_sha, g.provider "
        "FROM api_client_calls c LEFT JOIN git_repositories g ON c.repo = g.name WHERE 1=1"
    )
    params: List[Any] = []
    if repo_clean:
        sql += " AND c.repo = ?"
        params.append(repo_clean)
    sql += " ORDER BY c.repo ASC, c.filepath ASC, c.line_number ASC"
    rows = conn.execute(sql, params).fetchall()

    is_url_query = bool(clean_q and "/" in clean_q)
    belongs_to_target: Callable[[str, str], bool] = lambda _u, _m: True
    if is_url_query and clean_q:
        route_rows = conn.execute("SELECT repo, filepath, http_method, path_pattern FROM api_routes").fetchall()
        belongs_to_target = _target_ownership(clean_q, method_clean, route_rows)

    all_callers: List[Dict[str, Any]] = []
    seen_callers = set()
    q_low = clean_q.lower() if clean_q else None

    for c in rows:
        call_method = (c["http_method"] or "").upper()
        if method_clean and call_method and call_method != "ALL" and call_method != method_clean:
            continue

        url_pat = c["url_pattern"] or ""
        caller_sym = c["caller_symbol"] or ""
        if clean_q:
            if is_url_query:
                if not match_route_and_call(clean_q, url_pat) or not belongs_to_target(url_pat, call_method):
                    continue
            else:
                if q_low not in url_pat.lower() and q_low not in caller_sym.lower() and not match_route_and_call(clean_q, url_pat):
                    continue

        rel_path = local_roots.relative(c["filepath"], c["repo"])
        dedup_key = (c["repo"], rel_path, c["http_method"], url_pat, caller_sym, c["line_number"])
        if dedup_key in seen_callers:
            continue
        seen_callers.add(dedup_key)

        permalink = format_git_permalink(
            c["git_url"], c["commit_sha"], rel_path, c["line_number"], c["line_number"], provider=c["provider"]
        )
        all_callers.append({
            "repo": c["repo"],
            "method": c["http_method"],
            "url": url_pat,
            "caller": caller_sym,
            "file": rel_path,
            "line": c["line_number"],
            "permalink": permalink,
        })
    return all_callers


async def handle_find_routes(
    query: Annotated[Optional[str], Field(description="Optional route path, URL pattern, or handler/caller substring filter (e.g. '/api/v1/users/{id}' or 'checkout') across FastAPI, Flask, Django, Express/NestJS, ASP.NET Core, Go, Rust, Java, and frontend/service HTTP clients.")] = None,
    kind: Annotated[Literal["handlers", "callers", "both"], Field(description="Search server route 'handlers', client HTTP 'callers', or 'both' (default 'both').")] = "both",
    method: Annotated[Optional[str], Field(description="Optional HTTP verb filter (GET, POST, PUT, PATCH, DELETE).")] = None,
    repo: Annotated[Optional[str], Field(description="Optional repository name filter.")] = None,
    limit: Annotated[int, Field(description="Maximum results per section per page, clamped to 1..200 (default 50).")] = 50,
    offset: Annotated[int, Field(description="0-based offset for pagination (default 0). Advance via next_offset when has_more is True.")] = 0,
) -> str:
    """Discover HTTP/API route endpoints and/or client HTTP callers across indexed repositories with bounded pagination."""
    try:
        from app.services.auth import enforce_tool_permission, Role, ForbiddenError
        enforce_tool_permission(Role.VIEWER)

        clean_kind = (kind or "both").strip().lower()
        if clean_kind not in ("handlers", "callers", "both"):
            return json.dumps({"error": f"Unsupported kind '{kind}'. Valid kinds are 'handlers', 'callers', or 'both'."})

        clean_q = query.strip() if query and query.strip() else None
        method_clean = method.strip().upper() if method and method.strip() else None
        repo_clean = repo.strip() if repo and repo.strip() else None
        safe_limit = max(1, min(int(limit if limit is not None else 50), 200))
        safe_offset = max(0, int(offset if offset is not None else 0))

        with _get_tools_attr("get_db_connection", get_db_connection)() as conn:
            local_roots = LocalSourceRoots.load(conn)
            all_routes = (
                _query_route_handlers(conn, local_roots, clean_q, method_clean, repo_clean)
                if clean_kind in ("handlers", "both")
                else []
            )
            all_callers = (
                _query_route_callers(conn, local_roots, clean_q, method_clean, repo_clean)
                if clean_kind in ("callers", "both")
                else []
            )

        payload: Dict[str, Any] = {
            "query": clean_q,
            "kind": clean_kind,
            "method": method_clean,
            "repo": repo_clean,
            "offset": safe_offset,
            "limit": safe_limit,
        }

        if clean_kind == "handlers":
            total = len(all_routes)
            has_more = (safe_offset + safe_limit) < total
            payload.update({
                "total": total,
                "has_more": has_more,
                "next_offset": (safe_offset + safe_limit) if has_more else None,
                "routes": all_routes[safe_offset : safe_offset + safe_limit],
            })
        elif clean_kind == "callers":
            total = len(all_callers)
            has_more = (safe_offset + safe_limit) < total
            payload.update({
                "total": total,
                "has_more": has_more,
                "next_offset": (safe_offset + safe_limit) if has_more else None,
                "callers": all_callers[safe_offset : safe_offset + safe_limit],
            })
        else:
            total_routes = len(all_routes)
            total_callers = len(all_callers)
            routes_more = (safe_offset + safe_limit) < total_routes
            callers_more = (safe_offset + safe_limit) < total_callers
            has_more = routes_more or callers_more
            payload.update({
                "total": total_routes + total_callers,
                "total_routes": total_routes,
                "total_callers": total_callers,
                "has_more": has_more,
                "next_offset": (safe_offset + safe_limit) if has_more else None,
                "routes": all_routes[safe_offset : safe_offset + safe_limit],
                "callers": all_callers[safe_offset : safe_offset + safe_limit],
            })

        return json.dumps(payload)
    except ForbiddenError as fe:
        logger.warning(f"Forbidden error in handle_find_routes: {fe}")
        return json.dumps({"error": f"Forbidden: {str(fe)}", "forbidden": True})
    except Exception as e:
        logger.error(f"find_routes failed: {e}")
        return json.dumps({"error": f"Error searching API routes: {str(e)}"})
