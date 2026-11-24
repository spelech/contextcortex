import asyncio
import json
import logging
import sys
from typing import List, Dict, Any, Optional, Annotated, Tuple
from pydantic import Field

from app.services.database import get_db_connection
from app.services.indexing.sync_status import get_active_sync_status
from app.services.search import trace_symbol_path
from app.services.source_paths import LocalSourceRoots

logger = logging.getLogger("contextcortex")


def _get_tools_attr(name, default):
    t_mod = sys.modules.get("app.mcp.tools")
    return getattr(t_mod, name, default) if t_mod else default


def _strip_repo_prefix(filepath: Optional[str]) -> str:
    if not filepath:
        return ""
    res = filepath.split("://", 1)[1] if "://" in filepath else filepath
    return res.replace("\\", "/")


def _without_node_permalinks(nodes: List[Any]) -> List[Any]:
    """Copies trace nodes without their ~250-character permalinks (recursively through nested callers/callees)."""
    compact = []
    for node in nodes:
        if not isinstance(node, dict):
            compact.append(node)
            continue
        item = {key: value for key, value in node.items() if key != "permalink"}
        for nested in ("callers", "callees"):
            if isinstance(item.get(nested), list):
                item[nested] = _without_node_permalinks(item[nested])
        compact.append(item)
    return compact


def _paginate_trace_tree(
    nodes: List[Dict[str, Any]],
    child_key: str,
    offset: int,
    limit: int,
) -> Tuple[List[Dict[str, Any]], int]:
    """Counts total nodes in a BFS relationship tree and extracts a bounded [offset, offset + limit) window."""
    roots: List[Dict[str, Any]] = []
    counter = 0
    end_idx = offset + limit

    def _walk(items: List[Dict[str, Any]], active_parent: Optional[Dict[str, Any]]) -> None:
        nonlocal counter
        for item in items or []:
            idx = counter
            counter += 1
            children = item.get(child_key) or []
            if offset <= idx < end_idx:
                cloned = {k: v for k, v in item.items() if k != child_key}
                cloned[child_key] = []
                if active_parent is not None:
                    active_parent[child_key].append(cloned)
                else:
                    roots.append(cloned)
                _walk(children, cloned)
            else:
                _walk(children, None)

    _walk(nodes, None)
    return roots, counter


def _execute_find_symbol_sync(
    symbol: Optional[str], repo: Optional[str], exact: bool,
    limit: int, offset: int, name: Optional[str], query: Optional[str],
) -> str:
    sym_name = (symbol or name or query or "").strip()
    if not sym_name:
        return json.dumps({"error": "symbol name cannot be empty: pass 'symbol' (the alias 'name' is also accepted)."})

    try:
        from app.services.auth import enforce_tool_permission, Role, ForbiddenError
        enforce_tool_permission(Role.VIEWER)

        safe_limit = max(1, min(int(limit if limit is not None else 30), 100))
        safe_offset = max(0, int(offset if offset is not None else 0))

        with _get_tools_attr("get_db_connection", get_db_connection)() as conn:
            sql_query = (
                "SELECT repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language "
                "FROM ast_symbols WHERE "
            )
            params: List[Any] = []
            if exact:
                sql_query += "(name = ? OR full_symbol = ?)"
                params.extend([sym_name, sym_name])
            else:
                sql_query += "(name LIKE ? OR full_symbol LIKE ?)"
                params.extend([f"%{sym_name}%", f"%{sym_name}%"])
            if repo:
                sql_query += " AND repo = ?"
                params.append(repo)
            sql_query += " ORDER BY repo ASC, filepath ASC, start_line ASC, name ASC"
            rows = conn.execute(sql_query, params).fetchall()
            local_roots = LocalSourceRoots.load(conn)

        all_symbols = []
        seen_syms = set()
        for r in rows:
            rel_file = local_roots.relative(r["filepath"], r["repo"])
            sym_full = r["full_symbol"] or r["name"]
            dedup_key = (r["repo"], rel_file, r["name"], sym_full, r["kind"], r["start_line"], r["end_line"])
            if dedup_key in seen_syms:
                continue
            seen_syms.add(dedup_key)
            all_symbols.append({
                "name": r["name"], "symbol": sym_full, "kind": r["kind"], "repo": r["repo"],
                "file": rel_file, "lines": [r["start_line"], r["end_line"]],
                "signature": r["signature"], "language": r["language"],
            })

        total = len(all_symbols)
        paged_symbols = all_symbols[safe_offset : safe_offset + safe_limit]
        has_more = (safe_offset + safe_limit) < total
        next_offset = (safe_offset + safe_limit) if has_more else None

        payload = {
            "query": sym_name, "exact": exact, "total": total, "offset": safe_offset,
            "limit": safe_limit, "has_more": has_more, "next_offset": next_offset, "symbols": paged_symbols,
        }
        sync_info = get_active_sync_status(repo)
        if sync_info:
            payload.update(sync_info)
        return json.dumps(payload)
    except ForbiddenError as fe:
        logger.warning(f"Forbidden error in handle_find_symbol: {fe}")
        return json.dumps({"error": f"Forbidden: {str(fe)}", "forbidden": True})
    except Exception as e:
        logger.error(f"find_symbol error: {e}")
        return json.dumps({"error": f"Error finding symbol: {str(e)}"})


async def handle_find_symbol(
    symbol: Annotated[Optional[str], Field(description="Function, method, class, struct, interface, record, or COBOL paragraph name (or qualified name such as 'OrderService.create_order') across Python, TypeScript/JS/TSX, C#, COBOL, Go, Rust, Java, and C/C++. Same parameter name as trace_path.")] = None,
    repo: Annotated[Optional[str], Field(description="Optional repository name filter to restrict AST lookup.")] = None,
    exact: Annotated[bool, Field(description="Set True (default) for exact symbol/qualified-name match; False for substring/prefix matching.")] = True,
    limit: Annotated[int, Field(description="Maximum AST symbols per page, clamped to 1..100 (default 30).")] = 30,
    offset: Annotated[int, Field(description="0-based symbol offset for pagination (default 0). Advance via next_offset when has_more is True.")] = 0,
    name: Annotated[Optional[str], Field(description="Deprecated alias of `symbol`, kept for older callers. Use `symbol`; it wins when both are given.")] = None,
    query: Annotated[Optional[str], Field(description="Alias for `symbol`. `symbol` wins when both are given.")] = None,
) -> str:
    """Instant deterministic AST symbol lookup (functions, classes, methods, interfaces) without token-heavy full-file scans."""
    return await asyncio.to_thread(_execute_find_symbol_sync, symbol, repo, exact, limit, offset, name, query)


def _execute_trace_path_sync(
    symbol: Optional[str], repo: Optional[str], direction: str, depth: int,
    limit: int, offset: int, include_permalinks: bool, include_unresolved: bool,
    name: Optional[str], query: Optional[str],
) -> str:
    eff_symbol = (symbol if (symbol is not None and symbol.strip()) else (name or query or ""))
    try:
        from app.services.auth import enforce_tool_permission, Role, ForbiddenError
        enforce_tool_permission(Role.VIEWER)

        safe_limit = max(1, min(int(limit if limit is not None else 50), 200))
        safe_offset = max(0, int(offset if offset is not None else 0))
        fetch_cap = min(500, max(100, safe_offset + safe_limit + 25))

        trace_fn = _get_tools_attr("trace_symbol_path", trace_symbol_path)
        raw_res = trace_fn(
            symbol=eff_symbol, repo=repo, direction=direction, depth=depth,
            limit=fetch_cap, include_unresolved=bool(include_unresolved),
        )

        parsed: Optional[Dict[str, Any]] = None
        if isinstance(raw_res, dict):
            parsed = dict(raw_res)
        elif isinstance(raw_res, str):
            stripped = raw_res.strip()
            if stripped.startswith("{"):
                parsed = json.loads(stripped)
            elif stripped.startswith("["):
                return stripped
            elif stripped.startswith("Error:"):
                return json.dumps({"error": stripped})
            else:
                return json.dumps({"symbol": (eff_symbol or "").strip(), "repo": repo, "direction": direction, "depth": depth, "trace": raw_res})

        if parsed is None:
            return json.dumps({"result": raw_res})
        if "error" in parsed:
            return json.dumps(parsed, separators=(",", ":"))
        if parsed.get("found") is False:
            parsed.update({
                "total_callers": 0, "total_callees": 0, "offset": safe_offset,
                "limit": safe_limit, "has_more": False, "next_offset": None,
            })
            sync_info = get_active_sync_status(repo)
            if sync_info:
                parsed.update(sync_info)
            return json.dumps(parsed, separators=(",", ":"))

        paged_callers, total_callers = _paginate_trace_tree(parsed.get("callers") or [], "callers", safe_offset, safe_limit)
        paged_callees, total_callees = _paginate_trace_tree(parsed.get("callees") or [], "callees", safe_offset, safe_limit)
        has_more = (safe_offset + safe_limit) < total_callers or (safe_offset + safe_limit) < total_callees
        next_offset = (safe_offset + safe_limit) if has_more else None

        if not include_permalinks:
            paged_callers = _without_node_permalinks(paged_callers)
            paged_callees = _without_node_permalinks(paged_callees)
        parsed.update({
            "callers": paged_callers, "callees": paged_callees,
            "total_callers": total_callers, "total_callees": total_callees,
            "offset": safe_offset, "limit": safe_limit, "has_more": has_more,
            "next_offset": next_offset, "truncated": bool(has_more or parsed.get("truncated", False)),
        })
        sync_info = get_active_sync_status(repo)
        if sync_info:
            parsed.update(sync_info)
        return json.dumps(parsed, separators=(",", ":"))
    except ForbiddenError as fe:
        logger.warning(f"Forbidden error in handle_trace_path: {fe}")
        return json.dumps({"error": f"Forbidden: {str(fe)}", "forbidden": True})
    except Exception as e:
        logger.error(f"trace_path tool execution failed: {e}")
        return json.dumps({"error": f"Error executing trace_path: {str(e)}"})


async def handle_trace_path(
    symbol: Annotated[Optional[str], Field(description="Target function, method, or qualified class member (e.g. 'OrderService.create_order') across Python, TypeScript/JS/TSX, C#, COBOL, Go, Rust, Java, and C/C++.")] = None,
    repo: Annotated[Optional[str], Field(description="Optional repository name to scope intra-repo AST traversal (cross-repo HTTP boundaries still resolve automatically).")] = None,
    direction: Annotated[str, Field(description="Traversal direction: 'callers' (inbound), 'callees' (outbound), or 'both' (default 'both').")] = "both",
    depth: Annotated[int, Field(description="Maximum BFS hop depth, clamped to 1..5 (default 2).")] = 2,
    limit: Annotated[int, Field(description="Maximum caller/callee relationships per direction per page, clamped to 1..200 (default 50).")] = 50,
    offset: Annotated[int, Field(description="0-based relationship offset per direction for pagination (default 0). Advance via next_offset when has_more is True.")] = 0,
    include_permalinks: Annotated[bool, Field(description="Include a Git permalink on every caller/callee node (default False keeps answers compact; the target always has its permalink).")] = False,
    include_unresolved: Annotated[bool, Field(description="Show library calls (no indexed symbol) and calls into test code as tree nodes. Default False lists unresolved call names in a compact 'unresolved' list per node and drops test code for a production target.")] = False,
    name: Annotated[Optional[str], Field(description="Alias for `symbol`. `symbol` wins when both are given.")] = None,
    query: Annotated[Optional[str], Field(description="Alias for `symbol`. `symbol` wins when both are given.")] = None,
) -> str:
    """Traverse AST call graphs, imports, inheritance, and cross-repo HTTP route/client boundaries via bounded BFS."""
    return await asyncio.to_thread(
        _execute_trace_path_sync,
        symbol, repo, direction, depth, limit, offset, include_permalinks, include_unresolved, name, query,
    )


def handle_find_implementation_symbol(
    symbol: Annotated[str, Field(description="Function, method, or class name to locate across indexed repositories.")],
    repo: Annotated[Optional[str], Field(description="Optional target repository name.")] = None,
) -> str:
    """Workflow prompt to locate symbol definitions, line spans, and call graphs across registered codebases."""
    from app.services.auth import enforce_tool_permission, Role
    enforce_tool_permission(Role.VIEWER)
    return json.dumps({
        "prompt": "find_implementation_symbol",
        "symbol": symbol,
        "repo": repo,
        "recommended_tools": ["find_symbol", "read_file", "trace_path"],
        "instructions": (
            f"1. Call find_symbol(symbol='{symbol}', repo={json.dumps(repo)}, exact=True) (fall back to exact=False if not found) to get the file path and start/end lines.\n"
            f"2. Call read_file(path=..., repo=..., outline_only=True) to inspect surrounding structure or read_file(path=..., repo=..., start_line=..., end_line=...) to read the implementation without loading the whole file.\n"
            f"3. Call trace_path(symbol='{symbol}', repo={json.dumps(repo)}, direction='both', depth=2) to understand how '{symbol}' is called and what it invokes."
        ),
    })
