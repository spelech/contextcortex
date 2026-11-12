"""
Route specificity: give each client call to the most specific route that matches it.

A route parameter matches any segment, so `GET api/v{version}/assistants/{id}` also matches the call
`GET /api/v2/Assistants/details`. When the route `GET api/v{version}/assistants/details` exists in the same
repository, ASP.NET (and most other frameworks) send the call to that route: a literal segment beats a parameter.
These functions apply the same rule. `match_route_and_call` stays a plain yes/no matcher.
"""

import re
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.services.chunking.api_route_extractor import match_route_and_call, normalize_path_pattern

_PARAM_ONLY = re.compile(r'^\{[^{}/]+\}$')

# Segment ranks: a literal segment beats a mixed segment (`v{version}`), which beats a parameter (`{id}`).
_RANK_PARAM, _RANK_MIXED, _RANK_LITERAL = 0, 1, 2


@lru_cache(maxsize=4096)
def segment_ranks(path: str) -> Tuple[int, ...]:
    """Returns the rank of each segment of a route path, from left to right."""
    norm = normalize_path_pattern(re.sub(r'^https?://[^/]+', '', (path or '').strip("'\"` ")) or "/")
    segs = [s for s in norm.split("?", 1)[0].strip("/").split("/") if s]
    return tuple(
        _RANK_PARAM if _PARAM_ONLY.match(s) else _RANK_MIXED if "{" in s else _RANK_LITERAL
        for s in segs
    )


def compare_specificity(path_a: str, path_b: str) -> int:
    """
    Returns 1 when path_a is more specific than path_b, -1 when it is less specific, and 0 for a tie.
    Paths with the same number of segments are compared segment by segment from the left (the first segment where
    one path has a literal and the other a parameter decides). Paths of different length (a base-relative call
    can match both) are compared by their total literal weight; equal weight is a tie.
    """
    ranks_a, ranks_b = segment_ranks(path_a), segment_ranks(path_b)
    if len(ranks_a) == len(ranks_b):
        return (ranks_a > ranks_b) - (ranks_a < ranks_b)
    weight_a, weight_b = sum(ranks_a), sum(ranks_b)
    return (weight_a > weight_b) - (weight_a < weight_b)


def is_test_route_file(rel_path: str) -> bool:
    """True for a route declared in a test file or test folder (such routes never take calls from real routes)."""
    path_parts = [p.lower() for p in (rel_path or "").replace("\\", "/").strip("/").split("/") if p]
    bname = path_parts[-1] if path_parts else ""
    return (
        # test folders, including .NET test projects (`App.Tests`) and folders such as `Unit Tests`
        any(p in ("tests", "test", "__tests__") or p.endswith((".tests", ".test", " tests")) for p in path_parts[:-1])
        or bname.startswith("test_")
        or bname.endswith(("_test.py", ".test.ts", ".spec.ts", "tests.cs", "test.cs"))
    )


def methods_compatible(m1: Optional[str], m2: Optional[str]) -> bool:
    """An empty method or `ALL` is compatible with every method."""
    if not m1 or not m2:
        return True
    u1, u2 = m1.upper(), m2.upper()
    return u1 == "ALL" or u2 == "ALL" or u1 == u2


def route_key(route: Dict[str, Any]) -> Tuple[str, str, str]:
    """Identity of a route: repository, HTTP method, and normalized path."""
    return (
        route.get("repo") or "",
        (route.get("http_method") or "").upper(),
        normalize_path_pattern(route.get("path_pattern") or "").lower(),
    )


def most_specific_routes(
    call_url: str, call_method: Optional[str], routes: Iterable[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Returns the routes that own a call: the routes that match the call (path and method) and that no other matching
    route of the same repository beats on specificity. Each repository is resolved on its own, so a route in an
    unrelated repository never takes a call away from another repository's route. Ties keep all tied routes.
    """
    matches: Dict[str, List[Dict[str, Any]]] = {}
    for r in routes:
        if methods_compatible(r.get("http_method"), call_method) and match_route_and_call(r.get("path_pattern") or "", call_url):
            matches.setdefault(r.get("repo") or "", []).append(r)
    owners: List[Dict[str, Any]] = []
    for repo_matches in matches.values():
        for r in repo_matches:
            path = r.get("path_pattern") or ""
            if not any(compare_specificity(o.get("path_pattern") or "", path) > 0 for o in repo_matches):
                owners.append(r)
    return owners


def call_belongs_to_route(
    route: Dict[str, Any], call_url: str, call_method: Optional[str], routes: Iterable[Dict[str, Any]]
) -> bool:
    """
    True when the call matches `route` and no other route of the route's repository (with a compatible method)
    matches the call with more specificity. `routes` is the known route set; it can include `route` itself.
    """
    if not methods_compatible(route.get("http_method"), call_method):
        return False
    path = route.get("path_pattern") or ""
    if not match_route_and_call(path, call_url):
        return False
    repo = route.get("repo") or ""
    for other in routes:
        if (other.get("repo") or "") != repo or not methods_compatible(other.get("http_method"), call_method):
            continue
        other_path = other.get("path_pattern") or ""
        if compare_specificity(other_path, path) > 0 and match_route_and_call(other_path, call_url):
            return False
    return True
