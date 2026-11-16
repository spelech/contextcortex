"""Ranked call chain with evidence lines for `diagnose_issue`.

The chain starts at the entry points that the issue names (matched route handlers, stack-frame
symbols, matched symbols) and follows resolved production calls best-first. Each method gets a
score from the error terms in its body and in the line that calls it. A context argument that the
caller has (or the callee accepts) but the call does not pass, for example a `transaction`, adds a
bonus: that is a frequent cause of errors deep in a call path. The result is the path from an entry
point to the best-scoring method, with the call-site line and 1-3 evidence lines for each step.
"""

import heapq
import logging
from typing import Any, Dict, List, Optional, Tuple

from app.services.diagnostic_error_terms import line_term_hits, strong_terms
from app.services.file_reader import get_file_reader_service
from app.services.source_paths import LocalSourceRoots
from app.services.stack_trace_parser import _is_test_path

logger = logging.getLogger("contextcortex.diagnostics")

MAX_CHAIN_DEPTH = 6
MAX_NODES_READ = 60
MAX_ROOTS = 5
MAX_EVIDENCE_LINES = 3
MAX_LINE_CHARS = 160
MAX_CALL_SITE_LINES = 4
MAX_OTHER_HITS = 3
MAX_DETAIL_CODE_CHARS = 6000
BODY_SCORE_CAP = 12.0
DEPTH_PENALTY = 1.5
MISSING_CONTEXT_BONUS = 4.0
SUSPECT_BODY_SCORE = 6.0
HEADER_MAX_LINES = 8

_NON_CALLABLE_KINDS = ("class", "interface", "struct", "record", "enum", "type_alias", "constructor", "namespace")
_COMMENT_PREFIXES = ("//", "#", "*", "/*", "--")


def _callable(kind: Optional[str]) -> bool:
    k = (kind or "").lower()
    return not any(word in k for word in _NON_CALLABLE_KINDS)


def _sym(defn: Dict[str, Any]) -> str:
    return defn.get("full_symbol") or defn.get("name") or ""


class _SourceCache:
    """Reads each source file once and returns line slices."""

    def __init__(self):
        self._files: Dict[Tuple[str, str], List[str]] = {}
        self._reader = get_file_reader_service()

    def lines(self, defn: Dict[str, Any]) -> List[str]:
        key = (defn["repo"], defn["filepath"])
        if key not in self._files:
            try:
                content = self._reader.read_file(path=defn["filepath"], repo=defn["repo"]).get("content") or ""
            except Exception as e:
                logger.debug(f"Evidence chain could not read {defn['filepath']}: {e}")
                content = ""
            self._files[key] = content.splitlines()
        return self._files[key]

    def body(self, defn: Dict[str, Any]) -> List[Tuple[int, str]]:
        lines = self.lines(defn)
        start, end = int(defn["start_line"]), int(defn["end_line"])
        return [(n, lines[n - 1]) for n in range(start, min(end, len(lines)) + 1)]


class _Resolver:
    """Resolves call targets to indexed production definitions (no tests, no ambiguous library calls)."""

    def __init__(self, conn):
        self.conn = conn
        self._cache: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}

    def _rows(self, sql: str, params: List[Any]) -> List[Dict[str, Any]]:
        rows = [dict(r) for r in self.conn.execute(sql, params).fetchall()]
        return [r for r in rows if not _is_test_path(r["filepath"]) and _callable(r["kind"])]

    def _by_full(self, repo: str, full: str) -> List[Dict[str, Any]]:
        return self._rows(
            "SELECT id, repo, filepath, name, full_symbol, kind, start_line, end_line, signature FROM ast_symbols "
            "WHERE repo = ? AND (full_symbol = ? OR full_symbol LIKE ?) LIMIT 10",
            [repo, full, f"%.{full}"],
        )

    def _is_interface(self, repo: str, cls: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM ast_symbols WHERE repo = ? AND name = ? AND kind LIKE '%interface%' LIMIT 1",
            [repo, cls.split(".")[-1]],
        ).fetchone()
        return row is not None

    def _implementation(self, repo: str, iface: str, method: str) -> Optional[Dict[str, Any]]:
        """The one production implementation of an interface method, or None (none indexed, or more than one)."""
        short = iface.split(".")[-1]
        impls = self.conn.execute(
            "SELECT DISTINCT source_symbol FROM ast_relationships WHERE repo = ? AND relationship_type = 'IMPLEMENTS' "
            "AND (target_symbol = ? OR target_symbol LIKE ?)",
            [repo, short, f"%.{short}"],
        ).fetchall()
        found = []
        for row in impls:
            found.extend(self._by_full(repo, f"{row['source_symbol']}.{method}"))
        unique = {(d["filepath"], d["start_line"]): d for d in found}
        return next(iter(unique.values())) if len(unique) == 1 else None

    def resolve(self, repo: str, target: str, caller: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        key = (repo, target, _sym(caller or {}).rsplit(".", 1)[0])
        if key in self._cache:
            return self._cache[key]
        found: List[Dict[str, Any]] = []
        if "." in target:
            found = self._by_full(repo, target)
        else:
            owner = _sym(caller or {}).rsplit(".", 1)[0] if "." in _sym(caller or {}) else ""
            if owner:
                found = [d for d in self._by_full(repo, f"{owner}.{target}") if d["id"] != (caller or {}).get("id")]
            if not found:
                named = self._rows(
                    "SELECT id, repo, filepath, name, full_symbol, kind, start_line, end_line, signature FROM ast_symbols "
                    "WHERE repo = ? AND name = ? LIMIT 10",
                    [repo, target],
                )
                found = named if len({_sym(d) for d in named}) == 1 else []
        resolved = []
        for defn in found[:3]:
            cls, _, method = _sym(defn).rpartition(".")
            if cls and self._is_interface(repo, cls):
                impl = self._implementation(repo, cls, method)
                if impl:
                    resolved.append({**impl, "via": _sym(defn)})
                continue
            resolved.append(defn)
        self._cache[key] = resolved
        return resolved

    def find(self, symbol: str, repo: Optional[str]) -> Optional[Dict[str, Any]]:
        """Definition of an entry-point symbol (route handler, frame, or matched symbol)."""
        if not symbol:
            return None
        sql = ("SELECT id, repo, filepath, name, full_symbol, kind, start_line, end_line, signature FROM ast_symbols "
               "WHERE (full_symbol = ? OR full_symbol LIKE ?" + (" OR name = ?)" if "." not in symbol else ")"))
        params: List[Any] = [symbol, f"%.{symbol}"] + ([symbol] if "." not in symbol else [])
        if repo:
            sql += " AND repo = ?"
            params.append(repo)
        rows = self._rows(sql + " LIMIT 10", params)
        rows.sort(key=lambda r: (0 if _sym(r) == symbol else 1, int(r["end_line"]) - int(r["start_line"])))
        return rows[0] if rows else None

    def calls(self, defn: Dict[str, Any]) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT target_symbol, line_number FROM ast_relationships WHERE repo = ? AND source_filepath = ? "
            "AND relationship_type = 'CALLS' AND line_number >= ? AND line_number <= ? ORDER BY line_number ASC",
            [defn["repo"], defn["filepath"], defn["start_line"], defn["end_line"]],
        ).fetchall()
        seen, out = set(), []
        for r in rows:
            if r["target_symbol"] in seen or int(r["line_number"]) == int(defn["start_line"]):
                continue
            seen.add(r["target_symbol"])
            out.append({"target": r["target_symbol"], "line": int(r["line_number"])})
        return out


def _trim(text: str) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= MAX_LINE_CHARS else text[: MAX_LINE_CHARS - 3] + "..."


def _header(body: List[Tuple[int, str]]) -> str:
    """The declaration lines of a method (up to its opening brace, `=>`, or `:`)."""
    out = []
    for _, text in body[:HEADER_MAX_LINES]:
        out.append(text)
        stripped = text.strip()
        if "{" in stripped or "=>" in stripped or stripped.endswith(":"):
            break
    return " ".join(out)


def _call_site_text(lines: List[str], line_no: int) -> str:
    """The call line, extended over the next lines until the parentheses close."""
    parts, depth = [], 0
    for n in range(line_no, min(line_no + MAX_CALL_SITE_LINES, len(lines) + 1)):
        text = lines[n - 1]
        parts.append(text.strip())
        depth += text.count("(") - text.count(")")
        if depth <= 0:
            break
    return " ".join(parts)


def _evidence(body: List[Tuple[int, str]], terms: Dict[str, float]) -> Tuple[float, List[Dict[str, Any]]]:
    scored, matched = [], {}
    for n, text in body:
        if text.strip().startswith(_COMMENT_PREFIXES):
            continue
        hits = line_term_hits(text, terms)
        if hits:
            matched.update(hits)
            scored.append((-sum(hits.values()), n, text))
    best = sorted(scored)[:MAX_EVIDENCE_LINES]
    evidence = [{"line": n, "text": _trim(text)} for _, n, text in sorted(best, key=lambda x: x[1])]
    return min(BODY_SCORE_CAP, sum(matched.values())), evidence


def _missing_context(parent_header: str, child_header: str, call_text: str, terms: Dict[str, float]) -> List[str]:
    """Strong terms that the caller has or the callee accepts as a parameter, but the call does not pass."""
    call_hits = line_term_hits(call_text, terms)
    in_scope = {**line_term_hits(parent_header, terms), **line_term_hits(child_header, terms)}
    return sorted(t for t in strong_terms(in_scope) if t not in call_hits)


class _Node:
    __slots__ = ("defn", "parent", "depth", "score", "body_score", "path_score", "evidence", "call_site", "missing",
                 "body", "source", "order", "dropped")

    def __init__(self, defn, parent, depth, score, body_score, evidence, body, order, call_site=None, missing=None,
                 source=None):
        self.defn, self.parent, self.depth = defn, parent, depth
        self.score, self.body_score, self.evidence, self.body = score, body_score, evidence, body
        self.call_site, self.missing, self.source = call_site, missing or [], source
        self.path_score = (parent.path_score if parent else 0.0) + score - (DEPTH_PENALTY if parent else 0.0)
        # Execution-order key (root index, then the call-site line of each step) and "a context was dropped on the way".
        self.order = order
        self.dropped = bool(self.missing) or bool(parent and parent.dropped)


def _roots(resolver: _Resolver, matched_routes, resolved_frames, matched_symbols, repo) -> List[Tuple[Dict, str]]:
    roots: List[Tuple[Dict, str]] = []
    for route in matched_routes or []:
        handler = route.get("handler") or {}
        roots.append((resolver.find(handler.get("symbol"), handler.get("repo") or repo), "route_handler"))
    for frame in resolved_frames or []:
        if frame.get("symbol"):
            roots.append((resolver.find(frame["symbol"], frame.get("repo") if frame.get("repo") != "unknown" else repo), "stack_frame"))
    for match in matched_symbols or []:
        if _callable(match.get("kind")):
            roots.append((resolver.find(match.get("symbol"), match.get("repo") or repo), "matched_symbol"))
    unique: Dict[Any, Tuple[Dict, str]] = {}
    for defn, source in roots:
        if defn and defn["id"] not in unique:
            unique[defn["id"]] = (defn, source)
    return list(unique.values())[:MAX_ROOTS]


def _walk(resolver: _Resolver, cache: _SourceCache, roots, terms) -> Tuple[List[_Node], int]:
    nodes: List[_Node] = []
    heap: List[Tuple[float, int, int, _Node]] = []
    visited, reads = set(), 0
    for index, (defn, source) in enumerate(roots):
        body = cache.body(defn)
        reads += 1
        score, evidence = _evidence(body, terms)
        node = _Node(defn, None, 0, score, score, evidence, body, (index,), source=source)
        visited.add(defn["id"])
        nodes.append(node)
        heapq.heappush(heap, (-node.path_score, 0, len(nodes), node))
    while heap and reads < MAX_NODES_READ:
        _, _, _, parent = heapq.heappop(heap)
        if parent.depth >= MAX_CHAIN_DEPTH:
            continue
        parent_lines = cache.lines(parent.defn)
        parent_header = _header(parent.body)
        for call in resolver.calls(parent.defn):
            for defn in resolver.resolve(parent.defn["repo"], call["target"], parent.defn):
                if defn["id"] in visited or reads >= MAX_NODES_READ:
                    continue
                visited.add(defn["id"])
                body = cache.body(defn)
                reads += 1
                body_score, evidence = _evidence(body, terms)
                call_text = _call_site_text(parent_lines, call["line"])
                missing = _missing_context(parent_header, _header(body), call_text, terms)
                site_score = 0.5 * sum(line_term_hits(call_text, terms).values())
                score = body_score + site_score + (MISSING_CONTEXT_BONUS if missing else 0.0)
                node = _Node(defn, parent, parent.depth + 1, score, body_score, evidence, body, parent.order + (call["line"],),
                             call_site={"line": call["line"], "text": _trim(call_text)}, missing=missing)
                nodes.append(node)
                heapq.heappush(heap, (-node.path_score, call["line"], len(nodes), node))
    return nodes, reads


def _step(node: _Node, roots: LocalSourceRoots, detail: bool) -> Dict[str, Any]:
    defn = node.defn
    step: Dict[str, Any] = {
        "symbol": _sym(defn), "kind": defn.get("kind"),
        "file": roots.relative(defn["filepath"], defn["repo"]), "lines": [defn["start_line"], defn["end_line"]],
    }
    if defn.get("via"):
        step["via"] = defn["via"]
    if node.call_site:
        parent = node.parent.defn
        step["call_site"] = {"file": roots.relative(parent["filepath"], parent["repo"]), **node.call_site}
    if node.missing:
        step["not_passed"] = node.missing
    step["evidence"] = node.evidence
    step["score"] = round(node.score, 1)
    if detail:
        step["code"] = "\n".join(text for _, text in node.body)[:MAX_DETAIL_CODE_CHARS]
    return step


def _best_node(nodes: List[_Node]) -> _Node:
    """The end of the chain.

    A suspect is a method that does the failing kind of work (two or more strong terms in its body) below a call
    that dropped a context argument. An error stops at the first failing call, so the suspect that runs first
    (execution order) wins, and the chain goes to the deepest suspect below it. Without suspects, the method with
    the highest path score wins.
    """
    suspects = [n for n in nodes if n.dropped and n.body_score >= SUSPECT_BODY_SCORE]
    if suspects:
        first = min(suspects, key=lambda n: n.order)
        below = [n for n in suspects if n.order[: len(first.order)] == first.order]
        return max(below, key=lambda n: (n.depth, n.path_score))
    scored = [n for n in nodes if n.score > 0] or nodes[:1]
    return max(scored, key=lambda n: (n.path_score, n.depth))


def build_call_chain(
    conn,
    terms: Dict[str, float],
    matched_routes: Optional[List[Dict[str, Any]]] = None,
    resolved_frames: Optional[List[Dict[str, Any]]] = None,
    matched_symbols: Optional[List[Dict[str, Any]]] = None,
    repo: Optional[str] = None,
    detail: bool = False,
    roots_override: Optional[List[Tuple[Dict[str, Any], str]]] = None,
) -> Dict[str, Any]:
    """Returns {entry, terms, steps, other_hits, nodes_read}; steps run from the entry point to the best method."""
    resolver, cache = _Resolver(conn), _SourceCache()
    source_roots = LocalSourceRoots.load(conn)
    roots = roots_override if roots_override is not None else _roots(
        resolver, matched_routes, resolved_frames, matched_symbols, repo)
    result: Dict[str, Any] = {"entry": None, "terms": list(terms)[:12], "steps": [], "other_hits": [], "nodes_read": 0}
    if not roots:
        return result
    nodes, reads = _walk(resolver, cache, roots, terms)
    result["nodes_read"] = reads
    path, node = [], _best_node(nodes)
    while node:
        path.append(node)
        node = node.parent
    path.reverse()
    result["entry"] = path[0].source
    result["steps"] = [_step(n, source_roots, detail) for n in path]
    on_path = {id(n) for n in path}
    others = sorted((n for n in nodes if id(n) not in on_path and n.score > 0), key=lambda n: (not n.missing, -n.score))
    result["other_hits"] = [
        {"symbol": _sym(n.defn), "file": source_roots.relative(n.defn["filepath"], n.defn["repo"]),
         "lines": [n.defn["start_line"], n.defn["end_line"]], "score": round(n.score, 1),
         **({"not_passed": n.missing} if n.missing else {})}
        for n in others[:MAX_OTHER_HITS]
    ]
    return result


__all__ = ["build_call_chain", "MAX_CHAIN_DEPTH", "MAX_NODES_READ"]
