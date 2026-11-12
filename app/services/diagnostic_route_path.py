"""Route-path candidates and relevance filters for `diagnose_issue` semantic candidates.

When an HTTP route in the issue text matches an indexed route, the route handler and the
methods it calls (the call path below the handler) are the most likely places for the fault.
These candidates come before free-text semantic hits.
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional, Set

from app.services.graph_traversal import trace_symbol_path
from app.services.stack_trace_parser import _is_test_path

logger = logging.getLogger("contextcortex.diagnostics")

ROUTE_CALLEE_DEPTH = 3
MAX_ROUTE_TRACE_NODES = 40

_LANGUAGE_ALIASES = {
    "c_sharp": "csharp", "cs": "csharp", "c#": "csharp",
    "py": "python",
    "ts": "typescript", "tsx": "typescript",
    "js": "javascript", "jsx": "javascript", "mjs": "javascript", "cjs": "javascript",
    "cbl": "cobol", "cob": "cobol", "cpy": "cobol",
    "golang": "go", "rs": "rust",
    "cpp": "cpp", "cc": "cpp", "cxx": "cpp", "hpp": "cpp", "h": "cpp", "c": "cpp",
}
_CODE_EXTENSIONS = {"cs", "py", "ts", "tsx", "js", "jsx", "mjs", "cjs", "cbl", "cob", "cpy", "go", "rs",
                    "java", "cpp", "cc", "cxx", "hpp", "h", "c"}


def language_family(language: Optional[str], path: Optional[str] = None) -> Optional[str]:
    """Returns a normalized language name from a language tag, or from the file extension."""
    lang = (language or "").strip().lower()
    if lang and lang not in ("text", "unknown"):
        return _LANGUAGE_ALIASES.get(lang, lang)
    ext = os.path.splitext((path or "").lower())[1].lstrip(".")
    if ext in _CODE_EXTENSIONS:
        return _LANGUAGE_ALIASES.get(ext, ext)
    return None


def _walk_callees(nodes: List[Dict[str, Any]], depth: int, out: List[Dict[str, Any]]) -> None:
    """Flattens a trace_path callees tree in breadth-first order (nearest callees first)."""
    level = [(n, depth) for n in nodes]
    while level:
        nxt = []
        for node, d in level:
            out.append({"symbol": node.get("symbol"), "repo": node.get("repo"), "depth": d})
            nxt.extend((child, d + 1) for child in node.get("callees") or [])
        level = nxt


def _find_definition(conn, symbol: str, repo: Optional[str]) -> Optional[Dict[str, Any]]:
    """Finds the indexed definition of a symbol in the given repo (production code only)."""
    if not symbol:
        return None
    sql = (
        "SELECT repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language "
        "FROM ast_symbols WHERE (full_symbol = ?"
    )
    params: List[Any] = [symbol]
    if "." not in symbol:
        sql += " OR name = ?"
        params.append(symbol)
    sql += ")"
    if repo:
        sql += " AND repo = ?"
        params.append(repo)
    rows = [dict(r) for r in conn.execute(sql + " LIMIT 10", params).fetchall()]
    rows = [r for r in rows if not _is_test_path(r["filepath"])]
    if not rows:
        return None
    rows.sort(key=lambda r: (0 if r["full_symbol"] == symbol else 1, int(r["end_line"]) - int(r["start_line"])))
    return rows[0]


def collect_route_path_symbols(
    conn,
    matched_routes: List[Dict[str, Any]],
    repo: Optional[str] = None,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """Returns indexed definitions for matched route handlers and their callees, nearest first.

    Each item is an ast_symbols row with `source` ("route_handler" or "route_callee") and `depth`
    (0 for the handler). Calls that do not resolve to an indexed definition (framework or library
    calls) are skipped.
    """
    results: List[Dict[str, Any]] = []
    seen: Set[tuple] = set()

    def _add(defn: Optional[Dict[str, Any]], source: str, depth: int) -> None:
        if not defn or len(results) >= limit:
            return
        key = (defn["repo"], defn["full_symbol"] or defn["name"], defn["filepath"], defn["start_line"])
        if key in seen:
            return
        seen.add(key)
        results.append({**defn, "source": source, "depth": depth})

    handlers = []
    for route in matched_routes or []:
        handler = route.get("handler") or {}
        h_repo, h_sym = handler.get("repo"), handler.get("symbol")
        if not h_sym or (repo and h_repo != repo):
            continue
        defn = _find_definition(conn, h_sym, h_repo)
        _add(defn, "route_handler", 0)
        handlers.append((h_sym, h_repo, defn))

    for h_sym, h_repo, defn in handlers:
        if len(results) >= limit:
            break
        trace_sym = (defn["full_symbol"] or defn["name"]) if defn else h_sym
        try:
            trace = json.loads(trace_symbol_path(
                symbol=trace_sym, repo=h_repo, direction="callees",
                depth=ROUTE_CALLEE_DEPTH, limit=MAX_ROUTE_TRACE_NODES,
            ))
        except Exception as e:
            logger.debug(f"Could not trace callees of route handler {trace_sym}: {e}")
            continue
        flat: List[Dict[str, Any]] = []
        _walk_callees(trace.get("callees") or [], 1, flat)
        for node in flat:
            node_repo = node.get("repo") or h_repo
            if repo and node_repo != repo:
                continue
            _add(_find_definition(conn, node.get("symbol") or "", node_repo), "route_callee", node["depth"])
    return results


def keep_semantic_hit(
    payload: Dict[str, Any],
    repo: Optional[str],
    route_languages: Set[str],
) -> bool:
    """Drops semantic hits from other repos, test files, and (when a route matched) other languages."""
    hit_repo = payload.get("repo")
    if repo and hit_repo and hit_repo != repo:
        return False
    hit_path = payload.get("rel_path") or payload.get("path") or ""
    if hit_path and _is_test_path(hit_path):
        return False
    if route_languages:
        hit_lang = language_family(payload.get("language"), hit_path)
        if hit_lang and hit_lang not in route_languages:
            return False
    return True
