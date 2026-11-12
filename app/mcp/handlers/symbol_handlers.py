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

            query += f" LIMIT {max(limit * 3, limit)}"
            rows = conn.execute(query, params).fetchall()

        symbols = []
        seen_syms = set()
        for r in rows:
            rel_file = _strip_repo_prefix(r["filepath"])
            sym_full = r["full_symbol"] or r["name"]
            dedup_key = (r["repo"], rel_file, r["name"], sym_full, r["kind"], r["start_line"], r["end_line"])
            if dedup_key in seen_syms:
                continue
            seen_syms.add(dedup_key)
            symbols.append({
                "name": r["name"],
                "symbol": sym_full,
                "kind": r["kind"],
                "repo": r["repo"],
                "file": rel_file,
                "lines": [r["start_line"], r["end_line"]],
                "signature": r["signature"],
                "language": r["language"],
            })
            if len(symbols) >= limit:
                break

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
        import os
        candidates: List[str] = []
        matched_file = _strip_repo_prefix(fp)
        with _get_tools_attr("get_db_connection", get_db_connection)() as conn:
            def _query_outline_rows(target_clean: str):
                if repo:
                    return conn.execute(
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
                        (fp, target_clean, f"%/{target_clean}", f"%://{target_clean}", repo)
                    ).fetchall()
                else:
                    return conn.execute(
                        """
                        SELECT repo, filepath, name, full_symbol, kind, start_line, end_line, signature
                        FROM ast_symbols
                        WHERE REPLACE(filepath, '\\', '/') = ?
                           OR REPLACE(filepath, '\\', '/') = ?
                           OR REPLACE(filepath, '\\', '/') LIKE ?
                           OR REPLACE(filepath, '\\', '/') LIKE ?
                        ORDER BY start_line ASC
                        """,
                        (fp, target_clean, f"%/{target_clean}", f"%://{target_clean}")
                    ).fetchall()

            rows = _query_outline_rows(clean_fp)
            if rows:
                distinct_files = sorted({
                    _strip_repo_prefix(r["filepath"]) for r in rows if r["filepath"]
                })
                if len(distinct_files) > 1:
                    chosen_file = clean_fp if clean_fp in distinct_files else distinct_files[0]
                    rows = [r for r in rows if _strip_repo_prefix(r["filepath"]) == chosen_file]
                    matched_file = chosen_file
                    candidates = distinct_files

            # If an agent passed a prefixed path like 'src/McpRouter.Server/Program.cs' when the repo root is 'Program.cs',
            # progressively try shorter suffixes down to basename, resolving uniquely or surfacing candidates.
            if not rows and "/" in clean_fp:
                parts = [p for p in clean_fp.split("/") if p]
                for idx in range(1, len(parts)):
                    suffix = "/".join(parts[idx:])
                    cand_rows = _query_outline_rows(suffix)
                    if cand_rows:
                        distinct_files = sorted({
                            _strip_repo_prefix(r["filepath"]) for r in cand_rows if r["filepath"]
                        })
                        if len(distinct_files) == 1:
                            rows = cand_rows
                            matched_file = distinct_files[0]
                            break
                        else:
                            # Prefer root-level exact match if basename was at repo root
                            if suffix in distinct_files:
                                rows = [r for r in cand_rows if _strip_repo_prefix(r["filepath"]) == suffix]
                                matched_file = suffix
                                candidates = distinct_files
                                break
                            candidates = distinct_files
                            break

        resolved_repo = repo or (rows[0]["repo"] if rows and "repo" in rows[0].keys() else None)
        if rows and rows[0]["filepath"]:
            matched_file = _strip_repo_prefix(rows[0]["filepath"])

        symbols = []
        seen_syms = set()
        for r in rows:
            sym_full = r["full_symbol"] or r["name"]
            dedup_key = (r["name"], sym_full, r["kind"], r["start_line"], r["end_line"])
            if dedup_key in seen_syms:
                continue
            seen_syms.add(dedup_key)
            symbols.append({
                "name": r["name"],
                "symbol": sym_full,
                "kind": r["kind"],
                "lines": [r["start_line"], r["end_line"]],
                "signature": r["signature"],
            })

        result_payload: Dict[str, Any] = {
            "file": matched_file,
            "repo": resolved_repo,
            "symbols": symbols,
        }
        if candidates:
            result_payload["candidates"] = candidates
        return json.dumps(result_payload)
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
        "recommended_tools": ["find_symbol", "get_file_outline", "read_file", "trace_path"],
        "instructions": (
            f"1. Call find_symbol(name='{symbol}', repo={json.dumps(repo)}, exact=True) (fall back to exact=False if not found) to get the file path and start/end lines.\n"
            f"2. Call read_file(path=..., repo=..., start_line=..., end_line=...) using the exact line range returned by find_symbol to read the implementation without loading the whole file.\n"
            f"3. Call trace_path(symbol='{symbol}', repo={json.dumps(repo)}, direction='both', depth=2) to understand how '{symbol}' is called and what it invokes."
        ),
    })
