"""The trace_path answer for a target symbol that is not in the index.

A qualified name such as `AssistantInstanceReader.GetByInstanceId` must not fall back to every method that is
called `GetByInstanceId`: that merges the call graphs of unrelated classes. trace_path returns `found: false`
instead, with the indexed symbols that have the same member name, so the caller can retry with the right class.

The same source can be indexed as more than one repository (for example a git repository and a local copy of it).
Its symbols then have one row per repository with the same symbol, file, and line. The candidates merge these rows
into one entry with a `repos` list, so copies do not use the candidate slots.
"""

from typing import Any, Dict, List, Optional, Tuple

from app.services.source_paths import LocalSourceRoots

MAX_CANDIDATES = 10
# The rows read before the dedupe. Copies of a source use more than one row per candidate.
_MAX_ROWS = 1000


def _collect_candidates(rows, roots: LocalSourceRoots) -> List[Dict[str, Any]]:
    """Keeps the first MAX_CANDIDATES distinct (symbol, file, line) entries in row order, with the repos of each."""
    by_key: Dict[Tuple[str, str, Any], Dict[str, Any]] = {}
    for r in rows:
        entry = {"symbol": r["full_symbol"] or r["name"], "file": roots.relative(r["filepath"], r["repo"]), "line": r["start_line"]}
        key = (entry["symbol"], entry["file"], entry["line"])
        if key in by_key:
            if r["repo"] not in by_key[key]["repos"]:
                by_key[key]["repos"].append(r["repo"])
        elif len(by_key) < MAX_CANDIDATES:
            by_key[key] = {**entry, "repos": [r["repo"]]}
    return list(by_key.values())


def trace_not_found(conn, target_sym: str, short_target: str, repo: Optional[str]) -> Dict[str, Any]:
    result: Dict[str, Any] = {"symbol": target_sym, "found": False, "callers": [], "callees": []}
    if "." not in target_sym:
        return result
    repo_sql = " AND repo = ?" if repo else ""
    rows = conn.execute(
        "SELECT repo, filepath, full_symbol, name, start_line FROM ast_symbols WHERE LOWER(name) = LOWER(?)" + repo_sql
        + " ORDER BY full_symbol, start_line, repo LIMIT ?",
        [short_target] + ([repo] if repo else []) + [_MAX_ROWS],
    ).fetchall()
    candidates = _collect_candidates(rows, LocalSourceRoots.load(conn))
    if candidates:
        result["candidates"] = candidates
        result["hint"] = f"No indexed symbol is named {target_sym}. Call trace_path again with one of the candidates."
    return result


__all__ = ["trace_not_found", "MAX_CANDIDATES"]
