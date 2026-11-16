"""Comparison of the failing call chain with a similar path that still works, for `diagnose_issue`.

Bug reports often say that a similar action still works ("Publishing an assistant still works").
The sibling entry point is a route with the same shape where one literal segment is different
(`/tools/{id}/publish` -> `/assistants/{id}/publish`), or a method with the same name on a class
whose name has the working word instead of the failing word (`ToolService.PublishInstance` ->
`AssistantService.PublishInstance`). The sibling path follows the method names of the failing
chain step by step. The first step where the two paths are different is the most useful evidence.
"""

import re
from typing import Any, Dict, List, Optional, Tuple

from app.services.chunking import normalize_path_pattern
from app.services.diagnostic_error_terms import identifier_parts, line_term_hits
from app.services.diagnostic_evidence_chain import _call_site_text, _Resolver, _SourceCache, _sym, _trim
from app.services.source_paths import LocalSourceRoots

MAX_WORKING_STATEMENTS = 3

_WORKS = re.compile(
    r"\b(?:still\s+works?|works?\s+(?:fine|ok|okay|correctly|as expected|for)|works\b|succeeds?|is\s+(?:fine|ok|okay)"
    r"|are\s+(?:fine|ok|okay)|(?:does|do)\s*(?:n't|\s+not)\s+fail|no\s+problem)",
    re.IGNORECASE,
)
_NEGATED_WORK = re.compile(r"(?:\bnot|n't|\bnever|\bno longer)\s+(?:\w+\s+)?work", re.IGNORECASE)
_FAILS = re.compile(r"\bfail(?:s|ed|ing|ure)?\b", re.IGNORECASE)
_FILLER = {
    "still", "works", "work", "fine", "okay", "correctly", "expected", "succeeds", "succeed", "does", "fail", "problem",
    "the", "and", "for", "but", "with", "when", "from", "that", "this", "also", "same", "other", "are", "is", "an", "a",
}


def working_statements(issue_text: str) -> List[str]:
    """Sentences that say that something still works (without a negation such as "does not work")."""
    sentences = re.split(r"(?<=[.!?])\s+|\n+|[;,]|\b(?:but|while|whereas|although)\b", issue_text or "")
    found = []
    for sentence in sentences:
        text = sentence.strip(" >*-`")
        if text and _WORKS.search(text) and not _NEGATED_WORK.search(text) and not _FAILS.search(_WORKS.sub(" ", text)):
            found.append(text)
    return found[:MAX_WORKING_STATEMENTS]


def _stem(word: str) -> str:
    w = word.lower()
    for suffix in ("ies", "es", "s"):
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            return w[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return w


def _words(statement: str) -> List[str]:
    out = []
    for part in identifier_parts(statement):
        if len(part) >= 3 and part not in _FILLER and part not in out:
            out.append(part)
    return out


def _segments(path: str) -> List[str]:
    return [s for s in normalize_path_pattern(path or "").strip("/").split("/") if s]


def _sibling_route(conn, route: Dict[str, Any], words: List[str], repo: Optional[str]) -> Optional[Dict[str, Any]]:
    """A route with the same method and shape whose one different literal segment is a working word."""
    target = _segments(route.get("path"))
    stems = {_stem(w) for w in words}
    rows = conn.execute(
        "SELECT repo, http_method, path_pattern, handler_symbol FROM api_routes WHERE http_method = ?"
        + (" AND repo = ?" if repo else ""),
        [route.get("method")] + ([repo] if repo else []),
    ).fetchall()
    for r in rows:
        segs = _segments(r["path_pattern"])
        if len(segs) != len(target) or segs == target:
            continue
        diffs = [(a, b) for a, b in zip(target, segs) if a.lower() != b.lower()]
        if len(diffs) == 1 and "{" not in diffs[0][0] + diffs[0][1] and _stem(diffs[0][1]) in stems:
            return {**dict(r), "failing_word": diffs[0][0], "working_word": diffs[0][1]}
    return None


def _swap_class(cls: str, failing_stem: Optional[str], working: str) -> List[str]:
    """Class names with one camelCase part replaced by the working word (same singular/plural form)."""
    parts = re.findall(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z0-9]+|[A-Z]+", cls)
    out = []
    for i, part in enumerate(parts):
        if failing_stem and _stem(part) != failing_stem:
            continue
        word = _stem(working).capitalize()
        if part.lower() != _stem(part):
            word = word[:-1] + "ies" if word.endswith("y") else word + "s"
        if word.lower() != part.lower():
            out.append("".join(parts[:i] + [word] + parts[i + 1:]))
    return out


def _sibling_by_name(resolver: _Resolver, steps, words, failing_stem, repo) -> Optional[Tuple[int, Dict[str, Any]]]:
    """(index of the failing step, sibling definition) for the first step that has a same-name sibling method."""
    for index, step in enumerate(steps):
        owner, _, method = step["symbol"].rpartition(".")
        cls = owner.split(".")[-1]
        for word in words:
            for candidate in _swap_class(cls, failing_stem, word):
                defn = resolver.find(f"{candidate}.{method}", repo)
                if defn:
                    return index, defn
    return None


def _next_call(resolver: _Resolver, defn: Dict[str, Any], method: str):
    for call in resolver.calls(defn):
        if call["target"].rsplit(".", 1)[-1] != method:
            continue
        found = resolver.resolve(defn["repo"], call["target"], defn)
        if found:
            return found[0], call
    return None


def _brief(defn: Dict[str, Any], roots: LocalSourceRoots, call: Optional[Dict[str, Any]], lines: List[str]) -> Dict[str, Any]:
    out = {"symbol": _sym(defn), "file": roots.relative(defn["filepath"], defn["repo"]),
           "lines": [defn["start_line"], defn["end_line"]]}
    if call:
        out["call_site"] = {"line": call["line"], "text": _trim(_call_site_text(lines, call["line"]))}
    return out


def _passing_call(resolver, cache, defn, dropped: List[str], terms) -> Optional[Dict[str, Any]]:
    """The first call in a working method that passes a context argument that the failing path dropped."""
    lines = cache.lines(defn)
    for call in resolver.calls(defn):
        text = _call_site_text(lines, call["line"])
        if any(t in line_term_hits(text, terms) for t in dropped):
            return {"target": call["target"], "line": call["line"], "text": _trim(text)}
    return None


def compare_working_path(
    conn,
    issue_text: str,
    terms: Dict[str, float],
    chain: Dict[str, Any],
    matched_routes: Optional[List[Dict[str, Any]]] = None,
    repo: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Returns {statement, entry, steps, first_divergence}, or None when the issue names no working path."""
    steps = chain.get("steps") or []
    statements = working_statements(issue_text)
    if not steps or not statements:
        return None
    words = [w for s in statements for w in _words(s)]
    resolver, cache, roots = _Resolver(conn), _SourceCache(), LocalSourceRoots.load(conn)

    start, sibling, entry_route, failing_stem = 0, None, None, None
    for route in matched_routes or []:
        entry_route = _sibling_route(conn, route, words, repo)
        if entry_route:
            sibling = resolver.find(entry_route["handler_symbol"], entry_route["repo"])
            failing_stem = _stem(entry_route["failing_word"])
            words = [entry_route["working_word"]] + words
            break
    if not sibling:
        found = _sibling_by_name(resolver, steps, words, failing_stem, repo)
        if not found:
            return {"statement": statements[0], "entry": None, "steps": [], "first_divergence": None}
        start, sibling = found

    dropped = sorted({t for s in steps for t in s.get("not_passed") or []})
    result: Dict[str, Any] = {"statement": statements[0], "entry": {
        "symbol": _sym(sibling), "aligned_with": steps[start]["symbol"],
        **({"route": f"{entry_route['http_method']} {entry_route['path_pattern']}"} if entry_route else {}),
    }}
    aligned = [_brief(sibling, roots, None, [])]
    current, divergence = sibling, None
    for index in range(start + 1, len(steps)):
        failing = steps[index]
        nxt = _next_call(resolver, current, failing["symbol"].rsplit(".", 1)[-1])
        if not nxt:
            divergence = {"step": index, "reason": f"the working path does not call {failing['symbol'].rsplit('.', 1)[-1]} here",
                          "failing": {k: failing.get(k) for k in ("symbol", "file", "call_site")},
                          "working": {"symbol": aligned[-1]["symbol"],
                                      "passing_call": _passing_call(resolver, cache, current, dropped, terms)}}
            break
        defn, call = nxt
        brief = _brief(defn, roots, call, cache.lines(current))
        aligned.append(brief)
        lost = [t for t in failing.get("not_passed") or [] if t in line_term_hits(brief["call_site"]["text"], terms)]
        if lost:
            divergence = {"step": index, "reason": f"the failing call does not pass {', '.join(lost)}; the working call does",
                          "failing": {k: failing.get(k) for k in ("symbol", "file", "call_site")}, "working": brief}
            break
        current = defn
    if divergence:
        first_drop = next((s for s in steps[divergence["step"]:] if s.get("not_passed")), None)
        if first_drop:
            divergence["failing_drop"] = {k: first_drop.get(k) for k in ("symbol", "call_site", "not_passed")}
    result["steps"] = aligned
    result["first_divergence"] = divergence
    return result


__all__ = ["compare_working_path", "working_statements"]
