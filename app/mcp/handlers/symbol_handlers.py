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


def _strip_repo_prefix(filepath: Optional[str]) -> str:
    if not filepath:
        return ""
    res = filepath.split("://", 1)[1] if "://" in filepath else filepath
    return res.replace("\\", "/")


async def handle_find_symbol(
    name: Annotated[str, Field(description="Symbol name (e.g. 'extract_symbols_and_chunks' or 'FastAPI').")],
    repo: Annotated[Optional[str], Field(description="Optional repository filter.")] = None,
    exact: Annotated[bool, Field(description="If true, matches exact name. If false, prefix/fuzzy matches.")] = True,
    limit: Annotated[int, Field(description="Max results (default 10).")] = 10
) -> str:
    """Instant exact or prefix symbol lookup (functions, classes, structs, interfaces) from AST index without broad token scans."""
    sym_name = name.strip() if name else ""
    if not sym_name:
        return json.dumps({"error": "symbol name cannot be empty."})

    try:
        from app.services.auth import enforce_tool_permission, Role, ForbiddenError
        enforce_tool_permission(Role.VIEWER)
        with _get_tools_attr("get_db_connection", get_db_connection)() as conn:
            query = "SELECT repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language FROM ast_symbols WHERE "
            params = []
            if exact:
                query += "(name = ? OR full_symbol = ?)"
                params.extend([sym_name, sym_name])
            else:
                query += "(name LIKE ? OR full_symbol LIKE ?)"
                params.extend([f"%{sym_name}%", f"%{sym_name}%"])

            if repo:
                query += " AND repo = ?"
                params.append(repo)

            query += f" LIMIT {limit}"
            rows = conn.execute(query, params).fetchall()

        symbols = []
        for r in rows:
            symbols.append({
                "name": r["name"],
                "symbol": r["full_symbol"] or r["name"],
                "kind": r["kind"],
                "repo": r["repo"],
                "file": _strip_repo_prefix(r["filepath"]),
                "lines": [r["start_line"], r["end_line"]],
                "signature": r["signature"],
                "language": r["language"],
            })

        return json.dumps({
            "query": sym_name,
            "exact": exact,
            "symbols": symbols,
        })
    except ForbiddenError as fe:
        logger.warning(f"Forbidden error in handle_find_symbol: {fe}")
        return json.dumps({"error": f"Forbidden: {str(fe)}", "forbidden": True})
    except Exception as e:
        logger.error(f"find_symbol error: {e}")
        return json.dumps({"error": f"Error finding symbol: {str(e)}"})


async def handle_trace_path(
    symbol: Annotated[str, Field(description="The target function, method, or class name to trace.")],
    repo: Annotated[Optional[str], Field(description="Specific repository to trace within. If omitted, searches across all indexed repositories.")] = None,
    direction: Annotated[str, Field(description="Direction of traversal: 'callers' (inbound), 'callees' (outbound), or 'both' (default 'both').")] = "both",
    depth: Annotated[int, Field(description="Maximum hops in the BFS traversal (min 1, max 5, default 2).")] = 2,
    limit: Annotated[int, Field(description="Maximum total relationships returned to avoid token bloat (default 25).")] = 25
) -> str:
    """Deterministically traverse function call graphs, module imports, and inheritance hierarchies using AST relationships (BFS)."""
    try:
        from app.services.auth import enforce_tool_permission, Role, ForbiddenError
        enforce_tool_permission(Role.VIEWER)
        raw_res = trace_symbol_path(
            symbol=symbol,
            repo=repo,
            direction=direction,
            depth=depth,
            limit=limit
        )
        if isinstance(raw_res, dict):
            return json.dumps(raw_res)
        if isinstance(raw_res, str):
            stripped = raw_res.strip()
            if stripped.startswith("{") or stripped.startswith("["):
                return stripped
            if stripped.startswith("Error:"):
                return json.dumps({"error": stripped})
            return json.dumps({
                "symbol": (symbol or "").strip(),
                "repo": repo,
                "direction": direction,
                "depth": depth,
                "trace": raw_res,
            })
        return json.dumps({"result": raw_res})
    except ForbiddenError as fe:
        logger.warning(f"Forbidden error in handle_trace_path: {fe}")
        return json.dumps({"error": f"Forbidden: {str(fe)}", "forbidden": True})
    except Exception as e:
        logger.error(f"trace_path tool execution failed: {e}")
        return json.dumps({"error": f"Error executing trace_path: {str(e)}"})


async def handle_get_file_outline(
    filepath: Annotated[str, Field(description="File path (e.g. 'src/server.py' or 'repo_name://src/server.py').")],
    repo: Annotated[Optional[str], Field(description="Repository identifier (optional).")] = None
) -> str:
    """Get the AST outline (classes, methods, functions, line numbers) of a file without retrieving its entire token body."""
    fp = filepath.strip().replace("\\", "/") if filepath else ""
    clean_fp = fp.split("://", 1)[1].lstrip("/") if "://" in fp else fp.lstrip("/")
    try:
        from app.services.auth import enforce_tool_permission, Role, ForbiddenError
        enforce_tool_permission(Role.VIEWER)
        with _get_tools_attr("get_db_connection", get_db_connection)() as conn:
            if repo:
                rows = conn.execute(
                    """
                    SELECT repo, filepath, name, full_symbol, kind, start_line, end_line, signature
                    FROM ast_symbols
                    WHERE (
                        REPLACE(filepath, '\\', '/') = ?
                        OR REPLACE(filepath, '\\', '/') = ?
                        OR REPLACE(filepath, '\\', '/') LIKE ?
                        OR REPLACE(filepath, '\\', '/') LIKE ?
                    ) AND repo = ?
                    ORDER BY start_line ASC
                    """,
                    (fp, clean_fp, f"%/{clean_fp}", f"%://{clean_fp}", repo)
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT repo, filepath, name, full_symbol, kind, start_line, end_line, signature
                    FROM ast_symbols
                    WHERE REPLACE(filepath, '\\', '/') = ?
                       OR REPLACE(filepath, '\\', '/') = ?
                       OR REPLACE(filepath, '\\', '/') LIKE ?
                       OR REPLACE(filepath, '\\', '/') LIKE ?
                    ORDER BY start_line ASC
                    """,
                    (fp, clean_fp, f"%/{clean_fp}", f"%://{clean_fp}")
                ).fetchall()

        resolved_repo = repo or (rows[0]["repo"] if rows and "repo" in rows[0].keys() else None)
        symbols = []
        for r in rows:
            symbols.append({
                "name": r["name"],
                "symbol": r["full_symbol"] or r["name"],
                "kind": r["kind"],
                "lines": [r["start_line"], r["end_line"]],
                "signature": r["signature"],
            })

        return json.dumps({
            "file": _strip_repo_prefix(fp),
            "repo": resolved_repo,
            "symbols": symbols,
        })
    except ForbiddenError as fe:
        logger.warning(f"Forbidden error in handle_get_file_outline: {fe}")
        return json.dumps({"error": f"Forbidden: {str(fe)}", "forbidden": True})
    except Exception as e:
        return json.dumps({"error": f"Failed to get outline: {str(e)}"})


def handle_find_implementation_symbol(
    symbol: Annotated[str, Field(description="Function or class name to find")],
    repo: Annotated[Optional[str], Field(description="Target repository (optional)")] = None
) -> str:
    """Workflow to locate functions, classes, and logic across registered codebases."""
    from app.services.auth import enforce_tool_permission, Role
    enforce_tool_permission(Role.VIEWER)
    return json.dumps({
        "prompt": "find_implementation_symbol",
        "symbol": symbol,
        "repo": repo,
        "instructions": f"Use find_symbol for '{symbol}' in repo '{repo}' and inspect its declaration, line numbers, and implementation details.",
    })
