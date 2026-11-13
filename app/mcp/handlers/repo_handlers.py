import json
import logging
import sys
from typing import Any, Dict, List, Literal, Optional, Annotated
from pydantic import Field

from app.services.database import get_db_connection
from app.mcp.handlers.resource_handlers import handle_catalog_summary
from app.mcp.handlers.storage_handlers import (
    _strip_repo_prefix,
    build_source_file_slice,
    collect_index_status,
    collect_local_storage_entry,
)

logger = logging.getLogger("contextcortex")


def _get_tools_attr(name, default):
    t_mod = sys.modules.get("app.mcp.tools")
    return getattr(t_mod, name, default) if t_mod else default


async def handle_list_repositories(
    repo: Annotated[Optional[str], Field(description="Optional repository or storage namespace filter.")] = None,
    source_type: Annotated[Literal["all", "git", "monitored_path", "local_storage"], Field(description="Source filter: 'all' (default), 'git', 'monitored_path', or 'local_storage'.")] = "all",
    path_prefix: Annotated[Optional[str], Field(description="Optional file path substring/prefix filter when include_files=True (e.g. 'app/services').")] = None,
    file_extension: Annotated[Optional[str], Field(description="Optional file extension filter when include_files=True (e.g. '.py', '.ts', '.cs').")] = None,
    include_files: Annotated[bool, Field(description="Set True to include bounded, paginated file inventory per source and at top level (default False).")] = False,
    include_status: Annotated[bool, Field(description="Set True to include global vector store health, embedding models, counts, and Git provider auth status (default False).")] = False,
    limit: Annotated[int, Field(description="Maximum files returned per source and top-level page when include_files=True, clamped to 1..500 (default 100).")] = 100,
    offset: Annotated[int, Field(description="0-based file offset when include_files=True (default 0). Advance via next_offset when has_more is True.")] = 0,
) -> str:
    """List ingested Git repositories, monitored local paths, and optional file inventory or global index health status."""
    try:
        from app.services.auth import enforce_tool_permission, Role, ForbiddenError
        enforce_tool_permission(Role.VIEWER)

        st = (source_type or "all").strip().lower()
        if st not in ("all", "git", "monitored_path", "local_storage"):
            return json.dumps({"error": f"Unsupported source_type '{source_type}'. Valid values: 'all', 'git', 'monitored_path', 'local_storage'."})

        repo_name = repo.strip() if repo and repo.strip() else None
        want_files = bool(include_files)
        want_status = bool(include_status)
        safe_limit = max(1, min(int(limit if limit is not None else 100), 500))
        safe_offset = max(0, int(offset if offset is not None else 0))

        with _get_tools_attr("get_db_connection", get_db_connection)() as conn:
            git_repos = conn.execute(
                "SELECT id, name, url, branch, commit_sha, provider, status, last_synced FROM git_repositories"
            ).fetchall()
            local_paths = conn.execute(
                "SELECT path, repo, category FROM indexed_paths WHERE enabled = 1"
            ).fetchall()
            f_counts = conn.execute("SELECT repo, count(*) as cnt FROM indexed_files GROUP BY repo").fetchall()
            file_count_map = {c["repo"]: c["cnt"] for c in f_counts}
            s_counts = conn.execute("SELECT repo, count(*) as cnt FROM ast_symbols GROUP BY repo").fetchall()
            symbol_count_map = {s["repo"]: s["cnt"] for s in s_counts}

            matched_file_rows = []
            if want_files:
                query = "SELECT filepath, repo, doc_type, language, mtime FROM indexed_files WHERE 1=1"
                params: List[Any] = []
                if repo_name:
                    query += " AND repo = ?"
                    params.append(repo_name)
                if path_prefix:
                    query += " AND filepath LIKE ?"
                    params.append(f"%{path_prefix}%")
                if file_extension:
                    query += " AND filepath LIKE ?"
                    params.append(f"%{file_extension}%")
                query += " ORDER BY repo ASC, filepath ASC"
                matched_file_rows = conn.execute(query, params).fetchall()

        per_repo_paths: Dict[str, List[str]] = {}
        formatted_all_files: List[Dict[str, Any]] = []
        for df in matched_file_rows:
            r_key = df["repo"] or "unknown"
            clean_fp = _strip_repo_prefix(df["filepath"])
            per_repo_paths.setdefault(r_key, []).append(clean_fp)
            formatted_all_files.append({
                "repo": df["repo"],
                "file": clean_fp,
                "doc_type": df["doc_type"],
                "language": df["language"],
            })

        result: Dict[str, Any] = {
            "source_type": st,
            "include_files": want_files,
            "include_status": want_status,
        }

        if st in ("all", "git"):
            filtered_repos = [gr for gr in git_repos if not repo_name or gr["name"] == repo_name]
            repos_list = []
            for gr in filtered_repos:
                r_name = gr["name"]
                entry: Dict[str, Any] = {
                    "id": gr["id"],
                    "name": r_name,
                    "url": gr["url"],
                    "branch": gr["branch"],
                    "commit_sha": gr["commit_sha"],
                    "provider": (gr["provider"] or "git").lower(),
                    "status": gr["status"],
                    "files": file_count_map.get(r_name, 0),
                    "symbols": symbol_count_map.get(r_name, 0),
                    "last_synced": gr["last_synced"],
                }
                if want_files:
                    entry.update(build_source_file_slice(per_repo_paths.get(r_name, []), safe_offset, safe_limit))
                repos_list.append(entry)
            result["git_repositories"] = repos_list

        if st in ("all", "monitored_path"):
            filtered_paths = [lp for lp in local_paths if not repo_name or lp["repo"] == repo_name]
            monitored_list = []
            for lp in filtered_paths:
                r_name = lp["repo"]
                entry = {
                    "repo": r_name,
                    "path": lp["path"],
                    "category": lp["category"],
                    "files": file_count_map.get(r_name, 0),
                }
                if want_files:
                    entry.update(build_source_file_slice(per_repo_paths.get(r_name, []), safe_offset, safe_limit))
                monitored_list.append(entry)
            result["local_paths"] = monitored_list

        if st in ("all", "local_storage"):
            result["local_storage"] = collect_local_storage_entry(
                per_repo_paths=per_repo_paths,
                repo_file_counts=file_count_map,
                want_files=want_files,
                path_prefix=path_prefix,
                file_extension=file_extension,
                safe_offset=safe_offset,
                safe_limit=safe_limit,
            )

        if want_files:
            total_files = len(formatted_all_files)
            has_more = (safe_offset + safe_limit) < total_files
            result["total_files"] = total_files
            result["offset"] = safe_offset
            result["limit"] = safe_limit
            result["has_more"] = has_more
            result["next_offset"] = (safe_offset + safe_limit) if has_more else None
            result["files"] = formatted_all_files[safe_offset : safe_offset + safe_limit]

        if want_status:
            result.update(collect_index_status())

        return json.dumps(result, default=str)
    except ForbiddenError as fe:
        logger.warning(f"Forbidden error in handle_list_repositories: {fe}")
        return json.dumps({"error": f"Forbidden: {str(fe)}", "forbidden": True})
    except Exception as e:
        return json.dumps({"error": f"Error listing repositories: {str(e)}"})


def handle_search_infrastructure_docs(
    topic: Annotated[str, Field(description="Infrastructure topic, network route, or deployment subsystem to investigate.")],
) -> str:
    """Workflow prompt to search infrastructure documentation, ADRs, container mappings, and network routes."""
    from app.services.auth import enforce_tool_permission, Role
    enforce_tool_permission(Role.VIEWER)
    return json.dumps({
        "prompt": "search_infrastructure_docs",
        "topic": topic,
        "recommended_tools": ["search", "read_file", "grep_code"],
        "instructions": (
            f"1. Call search(query='{topic}', scope='docs', mode='hybrid') to locate relevant architecture notes, runbooks, and container configs.\n"
            f"2. Read resource knowledge://repo/{{repo}}/adrs to check if any Architectural Decision Records govern '{topic}'.\n"
            f"3. For the top matching files, call read_file(path=..., repo=..., start_line=..., end_line=...) to verify exact port mappings, environment variables, or reverse proxy routes before summarizing."
        ),
    })


def handle_onboard_repository(
    repo: Annotated[str, Field(description="Repository name to map out and onboard.")],
) -> str:
    """Structured workflow prompt to map a repository's architecture, routes, and AST outlines."""
    from app.services.auth import enforce_tool_permission, Role
    enforce_tool_permission(Role.VIEWER)
    return json.dumps({
        "prompt": "onboard_repository",
        "repo": repo,
        "recommended_tools": ["get_architecture", "find_routes", "read_file"],
        "instructions": (
            f"1. Call get_architecture(repo='{repo}') to inspect language distribution, manifests, entry points, primary modules, hub symbols, and active ADRs.\n"
            f"2. Call find_routes(repo='{repo}', kind='handlers') to enumerate exposed HTTP/API endpoints and their handler symbols.\n"
            f"3. For each entry point or hub symbol file, call read_file(path=..., repo='{repo}', outline_only=True) to map its classes and functions without reading entire files."
        ),
    })


def handle_triage_error(
    issue_text: Annotated[str, Field(description="Stack trace, exception message, or failing HTTP endpoint.")],
    repo: Annotated[Optional[str], Field(description="Optional target repository name.")] = None,
) -> str:
    """Forensic workflow prompt to diagnose stack traces or failing endpoints down to root-cause lines."""
    from app.services.auth import enforce_tool_permission, Role
    enforce_tool_permission(Role.VIEWER)
    return json.dumps({
        "prompt": "triage_error",
        "issue_text": issue_text,
        "repo": repo,
        "recommended_tools": ["diagnose_issue", "trace_path", "read_file"],
        "instructions": (
            f"1. Call diagnose_issue(issue_text={json.dumps(issue_text)}, repo={json.dumps(repo)}) to resolve stack frames, error string literals, matching routes, and semantic candidates.\n"
            f"2. For the primary resolved symbol, call trace_path(symbol=..., repo={json.dumps(repo)}, direction='both', depth=2) to inspect upstream callers and downstream callees.\n"
            f"3. Call read_file(path=..., repo=..., start_line=..., end_line=...) around the suspect lines to inspect error handling and state mutations."
        ),
    })


def handle_investigate_change_impact(
    symbol: Annotated[str, Field(description="Function, method, or class name being modified.")],
    repo: Annotated[Optional[str], Field(description="Optional repository name.")] = None,
) -> str:
    """Blast-radius workflow prompt to identify callers, cross-repo API consumers, and tests affected by modifying a symbol."""
    from app.services.auth import enforce_tool_permission, Role
    enforce_tool_permission(Role.VIEWER)
    return json.dumps({
        "prompt": "investigate_change_impact",
        "symbol": symbol,
        "repo": repo,
        "recommended_tools": ["find_symbol", "trace_path", "find_routes", "grep_code"],
        "instructions": (
            f"1. Call find_symbol(name='{symbol}', repo={json.dumps(repo)}, exact=True) to locate the symbol's exact file and line range.\n"
            f"2. Call trace_path(symbol='{symbol}', repo={json.dumps(repo)}, direction='callers', depth=3) to map all direct and transitive callers.\n"
            f"3. If the symbol handles or invokes an API route, call find_routes(query=..., kind='callers') to discover cross-repository client callers.\n"
            f"4. Call grep_code(pattern='{symbol}', repo={json.dumps(repo)}) to catch dynamic references, configuration bindings, and unit tests."
        ),
    })
