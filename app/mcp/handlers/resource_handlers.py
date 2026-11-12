import json
import logging
import sys
from typing import Any, Dict, List, Optional

from app.services.auth import enforce_tool_permission, Role, ForbiddenError
from app.services.database import get_db_connection, list_adrs
from app.services.git_manager import format_git_permalink
from app.mcp.handlers.architecture_handlers import handle_get_architecture
from app.mcp.handlers.route_handlers import _is_test_route_file

logger = logging.getLogger("contextcortex.mcp.resources")

FILES_PAGE_SIZE = 100
ROUTES_PAGE_SIZE = 50

RESOURCE_TEMPLATES_CATALOG: List[Dict[str, Any]] = [
    {
        "uri_template": "knowledge://repo/{repo}/summary",
        "name": "repo_summary",
        "description": "Repository status, commit SHA, file count, language distribution, symbol/route/ADR counts, and sub-resource URIs.",
    },
    {
        "uri_template": "knowledge://repo/{repo}/architecture",
        "name": "repo_architecture_overview",
        "description": "Synthesized architecture overview (languages, manifests, entry points, modules, hub symbols, routes, ADRs).",
    },
    {
        "uri_template": "knowledge://repo/{repo}/files/{page}",
        "name": "repo_files_page",
        "page_size": FILES_PAGE_SIZE,
        "description": "Paginated indexed file inventory (100 files per 1-indexed page).",
    },
    {
        "uri_template": "knowledge://repo/{repo}/routes/{page}",
        "name": "repo_routes_page",
        "page_size": ROUTES_PAGE_SIZE,
        "description": "Paginated HTTP/API routes (50 routes per 1-indexed page).",
    },
    {
        "uri_template": "knowledge://repo/{repo}/adrs",
        "name": "repo_adrs",
        "description": "Architecture Decision Records (ADRs) registered for the repository.",
    },
]


def _resolve_db_connection():
    t_mod = sys.modules.get("app.mcp.tools")
    if t_mod and hasattr(t_mod, "get_db_connection") and getattr(t_mod, "get_db_connection") is not get_db_connection:
        return getattr(t_mod, "get_db_connection")
    r_mod = sys.modules.get("app.mcp.handlers.repo_handlers")
    if r_mod and hasattr(r_mod, "get_db_connection") and getattr(r_mod, "get_db_connection") is not get_db_connection:
        return getattr(r_mod, "get_db_connection")
    if t_mod and hasattr(t_mod, "get_db_connection"):
        return getattr(t_mod, "get_db_connection")
    return get_db_connection


def _resolve_list_adrs():
    t_mod = sys.modules.get("app.mcp.tools")
    return getattr(t_mod, "list_adrs", list_adrs) if t_mod else list_adrs


def _strip_repo_prefix(filepath: Optional[str]) -> str:
    if not filepath:
        return ""
    res = filepath.split("://", 1)[1] if "://" in filepath else filepath
    return res.replace("\\", "/")


def _build_repo_sub_resources(repo_name: str) -> Dict[str, str]:
    return {
        "summary": f"knowledge://repo/{repo_name}/summary",
        "architecture": f"knowledge://repo/{repo_name}/architecture",
        "files_page_1": f"knowledge://repo/{repo_name}/files/1",
        "routes_page_1": f"knowledge://repo/{repo_name}/routes/1",
        "adrs": f"knowledge://repo/{repo_name}/adrs",
    }


def _parse_page_number(page: Any) -> int:
    try:
        parsed = int(str(page).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid page '{page}': page must be a 1-indexed integer.") from exc
    return max(1, parsed)


async def handle_catalog_summary() -> str:
    """Compact catalog of indexed repositories, symbol totals, sample files, and granular per-repo resource templates."""
    try:
        enforce_tool_permission(Role.VIEWER)
        with _resolve_db_connection()() as conn:
            git_repos = conn.execute(
                "SELECT name, url, branch, commit_sha, status, last_synced FROM git_repositories"
            ).fetchall()
            files = conn.execute("SELECT filepath, repo, doc_type, language FROM indexed_files").fetchall()
            symbols_count = conn.execute("SELECT count(*) FROM ast_symbols").fetchone()[0]
            try:
                sym_by_repo_rows = conn.execute("SELECT repo, count(*) as cnt FROM ast_symbols GROUP BY repo").fetchall()
                sym_by_repo = {r["repo"]: r["cnt"] for r in sym_by_repo_rows}
            except Exception:
                sym_by_repo = {}

        repo_file_counts: Dict[str, int] = {}
        repo_lang_counts: Dict[str, Dict[str, int]] = {}
        for f in files:
            r_name = f["repo"] or "unknown"
            lang = f["language"] or "text"
            repo_file_counts[r_name] = repo_file_counts.get(r_name, 0) + 1
            lang_map = repo_lang_counts.setdefault(r_name, {})
            lang_map[lang] = lang_map.get(lang, 0) + 1

        repos_data = []
        for gr in git_repos:
            r_name = gr["name"]
            repos_data.append({
                "name": r_name,
                "url": gr["url"],
                "branch": gr["branch"],
                "commit_sha": gr["commit_sha"],
                "status": gr["status"],
                "last_synced": gr["last_synced"],
                "files": repo_file_counts.get(r_name, 0),
                "symbols": sym_by_repo.get(r_name, 0),
                "languages": repo_lang_counts.get(r_name, {}),
                "sub_resources": _build_repo_sub_resources(r_name),
            })

        files_data = []
        for f in files[:40]:
            files_data.append({
                "repo": f["repo"],
                "file": _strip_repo_prefix(f["filepath"]),
                "doc_type": f["doc_type"],
                "language": f["language"],
            })

        return json.dumps({
            "total_files": len(files),
            "total_symbols": symbols_count,
            "git_repositories": repos_data,
            "files": files_data,
            "truncated_files": max(0, len(files) - 40),
            "resource_templates": RESOURCE_TEMPLATES_CATALOG,
        }, default=str)
    except ForbiddenError as fe:
        logger.warning(f"Forbidden error in handle_catalog_summary: {fe}")
        return json.dumps({"error": f"Forbidden: {str(fe)}", "forbidden": True})
    except Exception as e:
        return json.dumps({"error": f"Error generating catalog resource: {str(e)}"})


async def handle_repo_summary_resource(repo: str) -> str:
    """Per-repository summary resource with status, commit SHA, language breakdown, counts, and sub-resource URIs."""
    repo_clean = (repo or "").strip()
    try:
        enforce_tool_permission(Role.VIEWER)
        with _resolve_db_connection()() as conn:
            gr = conn.execute(
                "SELECT name, url, branch, commit_sha, provider, status, last_synced FROM git_repositories WHERE name = ?",
                (repo_clean,),
            ).fetchone()
            mon = conn.execute(
                "SELECT path, category FROM indexed_paths WHERE repo = ? AND enabled = 1",
                (repo_clean,),
            ).fetchall()
            file_rows = conn.execute(
                "SELECT language, count(*) as cnt FROM indexed_files WHERE repo = ? GROUP BY language",
                (repo_clean,),
            ).fetchall()
            symbol_count = conn.execute(
                "SELECT count(*) FROM ast_symbols WHERE repo = ?",
                (repo_clean,),
            ).fetchone()[0]
            route_rows = conn.execute(
                "SELECT filepath, http_method, path_pattern, start_line FROM api_routes WHERE repo = ?",
                (repo_clean,),
            ).fetchall()
            adr_count = conn.execute(
                "SELECT count(*) FROM architecture_decision_records WHERE repo = ?",
                (repo_clean,),
            ).fetchone()[0]

        languages: Dict[str, int] = {}
        file_count = 0
        for row in file_rows:
            lang = row["language"] or "text"
            cnt = int(row["cnt"] or 0)
            languages[lang] = cnt
            file_count += cnt

        seen_routes = set()
        for r in route_rows:
            rel_p = _strip_repo_prefix(r["filepath"])
            if _is_test_route_file(rel_p):
                continue
            seen_routes.add((r["http_method"], r["path_pattern"], rel_p, r["start_line"]))
        route_count = len(seen_routes)

        found = bool(gr or mon or file_count or symbol_count or route_count or adr_count)
        status_val = gr["status"] if gr else ("monitored" if mon or file_count else "not_found")

        return json.dumps({
            "repo": repo_clean,
            "found": found,
            "status": status_val,
            "url": gr["url"] if gr else None,
            "branch": gr["branch"] if gr else None,
            "commit_sha": gr["commit_sha"] if gr else None,
            "provider": (gr["provider"] or "git").lower() if gr else ("local" if mon else None),
            "last_synced": gr["last_synced"] if gr else None,
            "file_count": file_count,
            "total_files": file_count,
            "languages": languages,
            "symbol_count": symbol_count,
            "route_count": route_count,
            "adr_count": adr_count,
            "sub_resources": _build_repo_sub_resources(repo_clean),
        }, default=str)
    except ForbiddenError as fe:
        return json.dumps({"error": f"Forbidden: {str(fe)}", "forbidden": True})
    except Exception as e:
        logger.error(f"Error generating repo summary resource for '{repo_clean}': {e}")
        return json.dumps({"error": f"Error generating repository summary: {str(e)}"})


async def handle_repo_architecture_resource(repo: str) -> str:
    """Dynamic MCP resource template returning the synthesized architecture overview for a repository."""
    return await handle_get_architecture(repo=(repo or "").strip())


async def handle_repo_files_resource(repo: str, page: str = "1") -> str:
    """Paginated per-repository file inventory resource (100 files per 1-indexed page)."""
    repo_clean = (repo or "").strip()
    try:
        enforce_tool_permission(Role.VIEWER)
        page_num = _parse_page_number(page)

        with _resolve_db_connection()() as conn:
            rows = conn.execute(
                "SELECT filepath, doc_type, language FROM indexed_files WHERE repo = ? ORDER BY filepath ASC",
                (repo_clean,),
            ).fetchall()

        all_files = [
            {
                "file": _strip_repo_prefix(r["filepath"]),
                "doc_type": r["doc_type"],
                "language": r["language"],
            }
            for r in rows
        ]
        total_files = len(all_files)
        total_pages = (total_files + FILES_PAGE_SIZE - 1) // FILES_PAGE_SIZE
        start_idx = (page_num - 1) * FILES_PAGE_SIZE
        end_idx = start_idx + FILES_PAGE_SIZE
        page_items = all_files[start_idx:end_idx]
        has_more = end_idx < total_files
        next_uri = f"knowledge://repo/{repo_clean}/files/{page_num + 1}" if has_more else None

        return json.dumps({
            "repo": repo_clean,
            "page": page_num,
            "page_size": FILES_PAGE_SIZE,
            "total_files": total_files,
            "total_pages": total_pages,
            "has_more": has_more,
            "next_uri": next_uri,
            "files": page_items,
        }, default=str)
    except ForbiddenError as fe:
        return json.dumps({"error": f"Forbidden: {str(fe)}", "forbidden": True})
    except ValueError as ve:
        return json.dumps({"error": str(ve)})
    except Exception as e:
        logger.error(f"Error generating repo files resource for '{repo_clean}': {e}")
        return json.dumps({"error": f"Error generating repository files resource: {str(e)}"})


async def handle_repo_routes_resource(repo: str, page: str = "1") -> str:
    """Paginated per-repository API routes resource (50 routes per 1-indexed page)."""
    repo_clean = (repo or "").strip()
    try:
        enforce_tool_permission(Role.VIEWER)
        page_num = _parse_page_number(page)

        with _resolve_db_connection()() as conn:
            rows = conn.execute(
                """
                SELECT r.filepath, r.framework, r.http_method, r.path_pattern, r.handler_symbol,
                       r.start_line, r.end_line, g.url as git_url, g.commit_sha, g.provider
                FROM api_routes r
                LEFT JOIN git_repositories g ON r.repo = g.name
                WHERE r.repo = ?
                ORDER BY r.path_pattern ASC, r.http_method ASC, r.start_line ASC
                """,
                (repo_clean,),
            ).fetchall()

        all_routes = []
        seen = set()
        for r in rows:
            rel_path = _strip_repo_prefix(r["filepath"])
            if _is_test_route_file(rel_path):
                continue
            dedup_key = (r["http_method"], r["path_pattern"], rel_path, r["start_line"])
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            permalink = format_git_permalink(
                r["git_url"], r["commit_sha"], rel_path, r["start_line"], r["end_line"], provider=r["provider"]
            )
            all_routes.append({
                "method": r["http_method"],
                "path": r["path_pattern"],
                "framework": r["framework"],
                "handler": r["handler_symbol"],
                "file": rel_path,
                "lines": [r["start_line"], r["end_line"]],
                "permalink": permalink,
            })

        total_routes = len(all_routes)
        total_pages = (total_routes + ROUTES_PAGE_SIZE - 1) // ROUTES_PAGE_SIZE
        start_idx = (page_num - 1) * ROUTES_PAGE_SIZE
        end_idx = start_idx + ROUTES_PAGE_SIZE
        page_items = all_routes[start_idx:end_idx]
        has_more = end_idx < total_routes
        next_uri = f"knowledge://repo/{repo_clean}/routes/{page_num + 1}" if has_more else None

        return json.dumps({
            "repo": repo_clean,
            "page": page_num,
            "page_size": ROUTES_PAGE_SIZE,
            "total_routes": total_routes,
            "total_pages": total_pages,
            "has_more": has_more,
            "next_uri": next_uri,
            "routes": page_items,
        }, default=str)
    except ForbiddenError as fe:
        return json.dumps({"error": f"Forbidden: {str(fe)}", "forbidden": True})
    except ValueError as ve:
        return json.dumps({"error": str(ve)})
    except Exception as e:
        logger.error(f"Error generating repo routes resource for '{repo_clean}': {e}")
        return json.dumps({"error": f"Error generating repository routes resource: {str(e)}"})


async def handle_repo_adrs_resource(repo: str) -> str:
    """Per-repository Architecture Decision Records (ADRs) resource."""
    repo_clean = (repo or "").strip()
    try:
        enforce_tool_permission(Role.VIEWER)
        records = _resolve_list_adrs()(repo=repo_clean) or []
        adrs_out = []
        for r in records:
            ctx = r.get("context") or ""
            dec = r.get("decision") or ""
            cons = r.get("consequences") or ""
            adrs_out.append({
                "id": r.get("id"),
                "repo": r.get("repo", repo_clean),
                "title": r.get("title"),
                "status": r.get("status"),
                "superseded_by": r.get("superseded_by"),
                "context": ctx[:1000] + ("...[truncated]" if len(ctx) > 1000 else ""),
                "decision": dec[:1000] + ("...[truncated]" if len(dec) > 1000 else ""),
                "consequences": (cons[:1000] + ("...[truncated]" if len(cons) > 1000 else "")) if cons else None,
                "updated_at": r.get("updated_at"),
            })
        return json.dumps({
            "repo": repo_clean,
            "total_adrs": len(adrs_out),
            "adrs": adrs_out,
        }, default=str)
    except ForbiddenError as fe:
        return json.dumps({"error": f"Forbidden: {str(fe)}", "forbidden": True})
    except Exception as e:
        logger.error(f"Error generating repo ADRs resource for '{repo_clean}': {e}")
        return json.dumps({"error": f"Error generating repository ADRs resource: {str(e)}"})
