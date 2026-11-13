import json
import logging
import sys
from typing import Any, Dict, List, Optional, Annotated
from pydantic import Field

from app.services.auth import enforce_tool_permission, Role, ForbiddenError
from app.services.database import get_db_connection
from app.services.file_reader import get_file_reader_service
from app.services.source_paths import LocalSourceRoots
from app.mcp.handlers.grep_handlers import handle_grep_code

logger = logging.getLogger("contextcortex.mcp.files")


def _get_tools_attr(name, default):
    t_mod = sys.modules.get("app.mcp.tools")
    return getattr(t_mod, name, default) if t_mod else default


def _strip_repo_prefix(filepath: Optional[str]) -> str:
    if not filepath:
        return ""
    res = filepath.split("://", 1)[1] if "://" in filepath else filepath
    return res.replace("\\", "/")


def _read_file_outline_payload(
    path: str,
    repo: Optional[str],
    limit: int,
    offset: int,
) -> Dict[str, Any]:
    fp = path.strip().replace("\\", "/") if path else ""
    clean_fp = fp.split("://", 1)[1].lstrip("/") if "://" in fp else fp.lstrip("/")
    safe_limit = max(1, min(int(limit if limit is not None else 150), 500))
    safe_offset = max(0, int(offset if offset is not None else 0))

    candidates: List[str] = []
    matched_file = _strip_repo_prefix(fp)
    with _get_tools_attr("get_db_connection", get_db_connection)() as conn:
        local_roots = LocalSourceRoots.load(conn)

        def _rel(row) -> str:
            return local_roots.relative(row["filepath"], row["repo"])

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
            distinct_files = sorted({_rel(r) for r in rows if r["filepath"]})
            if len(distinct_files) > 1:
                chosen_file = clean_fp if clean_fp in distinct_files else distinct_files[0]
                rows = [r for r in rows if _rel(r) == chosen_file]
                matched_file = chosen_file
                candidates = distinct_files

        if not rows and "/" in clean_fp:
            parts = [p for p in clean_fp.split("/") if p]
            for idx in range(1, len(parts)):
                suffix = "/".join(parts[idx:])
                cand_rows = _query_outline_rows(suffix)
                if cand_rows:
                    distinct_files = sorted({_rel(r) for r in cand_rows if r["filepath"]})
                    if len(distinct_files) == 1:
                        rows = cand_rows
                        matched_file = distinct_files[0]
                        break
                    if suffix in distinct_files:
                        rows = [r for r in cand_rows if _rel(r) == suffix]
                        matched_file = suffix
                        candidates = distinct_files
                        break
                    candidates = distinct_files
                    break

    resolved_repo = repo or (rows[0]["repo"] if rows and "repo" in rows[0].keys() else None)
    if rows and rows[0]["filepath"]:
        matched_file = _rel(rows[0])

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
        "outline_only": True,
        "total_symbols": total_symbols,
        "offset": safe_offset,
        "limit": safe_limit,
        "has_more": has_more,
        "next_offset": next_offset,
        "symbols": paged_symbols,
    }
    if candidates:
        result_payload["candidates"] = candidates
    return result_payload


async def handle_read_file(
    path: Annotated[str, Field(description="Relative or absolute file path within an indexed repository, watched directory, or local storage (supports Python, TypeScript/JS/TSX, C#, COBOL, Go, Rust, Java, C/C++, Markdown, and config files).")],
    repo: Annotated[Optional[str], Field(description="Optional repository name or 'local_storage' namespace. Recommended for relative paths or reconstructing ephemeral Git files from vector chunks.")] = None,
    start_line: Annotated[Optional[int], Field(description="1-based inclusive starting line number (default 1). Pass next_start_line from a prior call to paginate long files.")] = None,
    end_line: Annotated[Optional[int], Field(description="1-based inclusive ending line number (default end of file, bounded by read_file_max_lines=2000 per call).")] = None,
    outline_only: Annotated[bool, Field(description="Set True to return the file's AST symbol outline (classes, methods, functions, signatures, line ranges) instead of full source text.")] = False,
    limit: Annotated[int, Field(description="Maximum AST symbols returned per page when outline_only=True, clamped to 1..500 (default 150).")] = 150,
    offset: Annotated[int, Field(description="0-based AST symbol offset when outline_only=True (default 0). Advance via next_offset when has_more is True.")] = 0,
) -> str:
    """Read bounded 1-based line slices or inspect the AST symbol outline (outline_only=True) for an indexed file."""
    try:
        enforce_tool_permission(Role.VIEWER)

        if outline_only:
            return json.dumps(_read_file_outline_payload(path=path, repo=repo, limit=limit, offset=offset))

        reader_fn = _get_tools_attr("get_file_reader_service", get_file_reader_service)
        reader = reader_fn()

        result = reader.read_file(
            path=path,
            repo=repo,
            start_line=start_line,
            end_line=end_line,
        )

        s_line = result.get("start_line")
        e_line = result.get("end_line")
        t_lines = result.get("total_lines")
        is_truncated = bool(result.get("truncated", False))
        has_more = bool(
            t_lines is not None
            and e_line is not None
            and t_lines > 0
            and e_line < t_lines
        )
        next_start_line = (e_line + 1) if (has_more and e_line is not None) else None

        return json.dumps({
            "file": _strip_repo_prefix(result.get("filepath") or path),
            "repo": repo,
            "source": result.get("source"),
            "lines": [s_line, e_line],
            "start_line": s_line,
            "end_line": e_line,
            "total_lines": t_lines,
            "has_more": has_more,
            "next_start_line": next_start_line,
            "size_bytes": result.get("size_bytes"),
            "truncated": is_truncated,
            "content": result.get("content", ""),
        })

    except ForbiddenError as fe:
        logger.warning(f"Forbidden error in handle_read_file ({path}): {fe}")
        return json.dumps({"error": f"Forbidden: {str(fe)}", "forbidden": True})
    except FileNotFoundError as fne:
        return json.dumps({"error": f"File not found: {str(fne)}"})
    except ValueError as ve:
        return json.dumps({"error": str(ve)})
    except Exception as e:
        logger.error(f"Error reading file '{path}': {e}")
        return json.dumps({"error": f"Error reading file: {str(e)}"})


__all__ = [
    "handle_read_file",
    "handle_grep_code",
]
