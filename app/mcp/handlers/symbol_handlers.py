import json
import logging
import sys
from typing import List, Dict, Any, Optional, Annotated, Tuple
from pydantic import Field

from app.services.database import get_db_connection
from app.services.search import trace_symbol_path

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


async def handle_find_symbol(
    name: Annotated[str, Field(description="Function, method, class, struct, interface, record, or COBOL paragraph name across Python, TypeScript/JS/TSX, C#, COBOL, Go, Rust, Java, and C/C++.")],
    repo: Annotated[Optional[str], Field(description="Optional repository name filter to restrict AST lookup.")] = None,
    exact: Annotated[bool, Field(description="Set True (default) for exact symbol/qualified-name match; False for substring/prefix matching.")] = True,
    limit: Annotated[int, Field(description="Maximum AST symbols per page, clamped to 1..100 (default 30).")] = 30,
    offset: Annotated[int, Field(description="0-based symbol offset for pagination (default 0). Advance via next_offset when has_more is True.")] = 0,
) -> str:
    """Instant deterministic AST symbol lookup (functions, classes, methods, interfaces) without token-heavy full-file scans."""
    sym_name = name.strip() if name else ""
    if not sym_name:
        return json.dumps({"error": "symbol name cannot be empty."})

    try:
        from app.services.auth import enforce_tool_permission, Role, ForbiddenError
        enforce_tool_permission(Role.VIEWER)

        safe_limit = max(1, min(int(limit if limit is not None else 30), 100))
        safe_offset = max(0, int(offset if offset is not None else 0))

        with _get_tools_attr("get_db_connection", get_db_connection)() as conn:
            query = (
                "SELECT repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language "
                "FROM ast_symbols WHERE "
            )
            params: List[Any] = []
            if exact:
                query += "(name = ? OR full_symbol = ?)"
                params.extend([sym_name, sym_name])
            else:
                query += "(name LIKE ? OR full_symbol LIKE ?)"
                params.extend([f"%{sym_name}%", f"%{sym_name}%"])

            if repo:
                query += " AND repo = ?"
                params.append(repo)

            query += " ORDER BY repo ASC, filepath ASC, start_line ASC, name ASC"
            rows = conn.execute(query, params).fetchall()

        all_symbols = []
        seen_syms = set()
        for r in rows:
            rel_file = _strip_repo_prefix(r["filepath"])
            sym_full = r["full_symbol"] or r["name"]
            dedup_key = (r["repo"], rel_file, r["name"], sym_full, r["kind"], r["start_line"], r["end_line"])
            if dedup_key in seen_syms:
                continue
            seen_syms.add(dedup_key)
            all_symbols.append({
                "name": r["name"],
                "symbol": sym_full,
                "kind": r["kind"],
                "repo": r["repo"],
                "file": rel_file,
                "lines": [r["start_line"], r["end_line"]],
                "signature": r["signature"],
                "language": r["language"],
            })

        total = len(all_symbols)
        paged_symbols = all_symbols[safe_offset : safe_offset + safe_limit]
        has_more = (safe_offset + safe_limit) < total
        next_offset = (safe_offset + safe_limit) if has_more else None

        return json.dumps({
            "query": sym_name,
            "exact": exact,
            "total": total,
            "offset": safe_offset,
            "limit": safe_limit,
            "has_more": has_more,
            "next_offset": next_offset,
            "symbols": paged_symbols,
        })
    except ForbiddenError as fe:
        logger.warning(f"Forbidden error in handle_find_symbol: {fe}")
        return json.dumps({"error": f"Forbidden: {str(fe)}", "forbidden": True})
    except Exception as e:
        logger.error(f"find_symbol error: {e}")
        return json.dumps({"error": f"Error finding symbol: {str(e)}"})


async def handle_trace_path(
    symbol: Annotated[str, Field(description="Target function, method, or qualified class member (e.g. 'OrderService.create_order') across Python, TypeScript/JS/TSX, C#, COBOL, Go, Rust, Java, and C/C++.")],
    repo: Annotated[Optional[str], Field(description="Optional repository name to scope intra-repo AST traversal (cross-repo HTTP boundaries still resolve automatically).")] = None,
    direction: Annotated[str, Field(description="Traversal direction: 'callers' (inbound), 'callees' (outbound), or 'both' (default 'both').")] = "both",
    depth: Annotated[int, Field(description="Maximum BFS hop depth, clamped to 1..5 (default 2).")] = 2,
    limit: Annotated[int, Field(description="Maximum caller/callee relationships per direction per page, clamped to 1..200 (default 50).")] = 50,
    offset: Annotated[int, Field(description="0-based relationship offset per direction for pagination (default 0). Advance via next_offset when has_more is True.")] = 0,
    include_permalinks: Annotated[bool, Field(description="Include a Git permalink on every caller/callee node (default False keeps answers compact; the target always has its permalink).")] = False,
) -> str:
    """Traverse AST call graphs, imports, inheritance, and cross-repo HTTP route/client boundaries via bounded BFS."""
    try:
        from app.services.auth import enforce_tool_permission, Role, ForbiddenError
        enforce_tool_permission(Role.VIEWER)

        safe_limit = max(1, min(int(limit if limit is not None else 50), 200))
        safe_offset = max(0, int(offset if offset is not None else 0))
        fetch_cap = max(1000, (safe_offset + safe_limit) * 2 + 50)

        trace_fn = _get_tools_attr("trace_symbol_path", trace_symbol_path)
        raw_res = trace_fn(
            symbol=symbol,
            repo=repo,
            direction=direction,
            depth=depth,
            limit=fetch_cap,
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
                return json.dumps({
                    "symbol": (symbol or "").strip(),
                    "repo": repo,
                    "direction": direction,
                    "depth": depth,
                    "trace": raw_res,
                })

        if parsed is None:
            return json.dumps({"result": raw_res})

        if "error" in parsed:
            return json.dumps(parsed, separators=(",", ":"))

        if parsed.get("found") is False:
            parsed.update({
                "total_callers": 0,
                "total_callees": 0,
                "offset": safe_offset,
                "limit": safe_limit,
                "has_more": False,
                "next_offset": None,
            })
            return json.dumps(parsed, separators=(",", ":"))

        paged_callers, total_callers = _paginate_trace_tree(
            parsed.get("callers") or [], "callers", safe_offset, safe_limit
        )
        paged_callees, total_callees = _paginate_trace_tree(
            parsed.get("callees") or [], "callees", safe_offset, safe_limit
        )
        callers_more = (safe_offset + safe_limit) < total_callers
        callees_more = (safe_offset + safe_limit) < total_callees
        has_more = callers_more or callees_more
        next_offset = (safe_offset + safe_limit) if has_more else None

        if not include_permalinks:
            paged_callers = _without_node_permalinks(paged_callers)
            paged_callees = _without_node_permalinks(paged_callees)
        parsed["callers"] = paged_callers
        parsed["callees"] = paged_callees
        parsed["total_callers"] = total_callers
        parsed["total_callees"] = total_callees
        parsed["offset"] = safe_offset
        parsed["limit"] = safe_limit
        parsed["has_more"] = has_more
        parsed["next_offset"] = next_offset
        parsed["truncated"] = bool(has_more or parsed.get("truncated", False))
        return json.dumps(parsed, separators=(",", ":"))
    except ForbiddenError as fe:
        logger.warning(f"Forbidden error in handle_trace_path: {fe}")
        return json.dumps({"error": f"Forbidden: {str(fe)}", "forbidden": True})
    except Exception as e:
        logger.error(f"trace_path tool execution failed: {e}")
        return json.dumps({"error": f"Error executing trace_path: {str(e)}"})


async def handle_get_file_outline(
    filepath: Annotated[str, Field(description="Relative or repo-prefixed file path (e.g. 'app/main.py' or 'my-repo://Program.cs') across Python, TypeScript/JS/TSX, C#, COBOL, Go, Rust, Java, and C/C++.")],
    repo: Annotated[Optional[str], Field(description="Optional repository identifier to disambiguate identical filenames across repos.")] = None,
    limit: Annotated[int, Field(description="Maximum AST symbols returned per page, clamped to 1..500 (default 150).")] = 150,
    offset: Annotated[int, Field(description="0-based symbol offset for pagination (default 0). Advance via next_offset when has_more is True.")] = 0,
) -> str:
    """Return the structural AST outline (classes, methods, functions, signatures, line ranges) of a file with bounded pagination."""
    fp = filepath.strip().replace("\\", "/") if filepath else ""
    clean_fp = fp.split("://", 1)[1].lstrip("/") if "://" in fp else fp.lstrip("/")
    try:
        from app.services.auth import enforce_tool_permission, Role, ForbiddenError
        enforce_tool_permission(Role.VIEWER)

        safe_limit = max(1, min(int(limit if limit is not None else 150), 500))
        safe_offset = max(0, int(offset if offset is not None else 0))

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
                        (fp, target_clean, f"%/{target_clean}", f"%://{target_clean}", repo),
                    ).fetchall()
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
                    (fp, target_clean, f"%/{target_clean}", f"%://{target_clean}"),
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

        all_symbols = []
        seen_syms = set()
        for r in rows:
            sym_full = r["full_symbol"] or r["name"]
            dedup_key = (r["name"], sym_full, r["kind"], r["start_line"], r["end_line"])
            if dedup_key in seen_syms:
                continue
            seen_syms.add(dedup_key)
            all_symbols.append({
                "name": r["name"],
                "symbol": sym_full,
                "kind": r["kind"],
                "lines": [r["start_line"], r["end_line"]],
                "signature": r["signature"],
            })

        total_symbols = len(all_symbols)
        paged_symbols = all_symbols[safe_offset : safe_offset + safe_limit]
        has_more = (safe_offset + safe_limit) < total_symbols
        next_offset = (safe_offset + safe_limit) if has_more else None

        result_payload: Dict[str, Any] = {
            "file": matched_file,
            "repo": resolved_repo,
            "total_symbols": total_symbols,
            "offset": safe_offset,
            "limit": safe_limit,
            "has_more": has_more,
            "next_offset": next_offset,
            "symbols": paged_symbols,
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
        "recommended_tools": ["find_symbol", "get_file_outline", "read_file", "trace_path"],
        "instructions": (
            f"1. Call find_symbol(name='{symbol}', repo={json.dumps(repo)}, exact=True) (fall back to exact=False if not found) to get the file path and start/end lines.\n"
            f"2. Call read_file(path=..., repo=..., start_line=..., end_line=...) using the exact line range returned by find_symbol to read the implementation without loading the whole file.\n"
            f"3. Call trace_path(symbol='{symbol}', repo={json.dumps(repo)}, direction='both', depth=2) to understand how '{symbol}' is called and what it invokes."
        ),
    })
