"""The trace_path answer for a target symbol that is not in the index.

A qualified name such as `AssistantInstanceReader.GetByInstanceId` must not fall back to every method that is
called `GetByInstanceId`: that merges the call graphs of unrelated classes. trace_path returns `found: false`
instead, with the indexed symbols that have the same member name, so the caller can retry with the right class.
"""

from typing import Any, Dict, Optional

from app.services.source_paths import LocalSourceRoots

MAX_CANDIDATES = 10


def trace_not_found(conn, target_sym: str, short_target: str, repo: Optional[str]) -> Dict[str, Any]:
    result: Dict[str, Any] = {"symbol": target_sym, "found": False, "callers": [], "callees": []}
    if "." not in target_sym:
        return result
    repo_sql = " AND repo = ?" if repo else ""
    rows = conn.execute(
        "SELECT repo, filepath, full_symbol, name, start_line FROM ast_symbols WHERE LOWER(name) = LOWER(?)" + repo_sql
        + " ORDER BY full_symbol LIMIT ?",
        [short_target] + ([repo] if repo else []) + [MAX_CANDIDATES],
    ).fetchall()
    if rows:
        roots = LocalSourceRoots.load(conn)
        result["candidates"] = [
            {"symbol": r["full_symbol"] or r["name"], "file": roots.relative(r["filepath"], r["repo"]), "line": r["start_line"]}
            for r in rows
        ]
        result["hint"] = f"No indexed symbol is named {target_sym}. Call trace_path again with one of the candidates."
    return result


__all__ = ["trace_not_found", "MAX_CANDIDATES"]
