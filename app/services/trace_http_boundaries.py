"""Cross-repository HTTP boundaries of a trace_path node: the route it handles, external callers, and outbound calls."""

from typing import Callable, Dict, List, Optional

from app.services.chunking.route_specificity import call_belongs_to_route, is_test_route_file


def make_http_boundary_resolver(all_routes: List[dict], all_calls: List[dict], _rel_path: Callable[[Optional[str]], str]):
    """Returns `resolve_http_boundaries(sym_name, sym_repo) -> (route_meta, external_callers, http_calls)`."""
    # Routes that compete for a call, per repository (routes in test files never take a call from a real route).
    competing_routes: Dict[str, List[dict]] = {}
    for r in all_routes:
        if not is_test_route_file(_rel_path(r.get("filepath"))):
            competing_routes.setdefault(r.get("repo") or "", []).append(r)

    def _owns_call(route: dict, call_url: str, call_method: Optional[str]) -> bool:
        return call_belongs_to_route(route, call_url, call_method, competing_routes.get(route.get("repo") or "", []))

    def resolve_http_boundaries(sym_name: str, sym_repo: str):
        route_meta, ext_callers, http_calls = None, [], []
        short_s = sym_name.split(".")[-1]
        matched_routes = [
            r for r in all_routes
            if (r.get("repo") == sym_repo or not sym_repo)
            and (r.get("handler_symbol") == sym_name or (r.get("handler_symbol") and (r["handler_symbol"] == short_s or sym_name.endswith(f".{r['handler_symbol']}"))))
        ]
        if matched_routes:
            route_meta = {"method": matched_routes[0]["http_method"].upper(), "path": matched_routes[0]["path_pattern"]}
            for r_item in matched_routes:
                # A call belongs to this route only when no more specific route of the same repository matches it.
                for c in all_calls:
                    if c["repo"] != sym_repo and _owns_call(r_item, c.get("url_pattern", ""), c.get("http_method")):
                        entry = {"repo": c["repo"], "symbol": c.get("caller_symbol") or "", "file": _rel_path(c["filepath"]), "line": c.get("line_number"), "method": c.get("http_method", "").upper(), "url": c.get("url_pattern", "")}
                        if entry not in ext_callers:
                            ext_callers.append(entry)

        matched_calls = [
            c for c in all_calls
            if (c.get("repo") == sym_repo or not sym_repo)
            and (c.get("caller_symbol") == sym_name or (c.get("caller_symbol") and (c["caller_symbol"] == short_s or sym_name.endswith(f".{c['caller_symbol']}"))))
        ]
        for c in matched_calls:
            c_method, c_url = c.get("http_method", "").upper(), c.get("url_pattern", "")
            ext_handlers = []
            for r in all_routes:
                # Per repository, only the most specific matching route handles the call.
                if r["repo"] == sym_repo or not _owns_call(r, c_url, c_method):
                    continue
                h_entry = {"repo": r["repo"], "symbol": r.get("handler_symbol") or "", "file": _rel_path(r["filepath"]), "line": r.get("start_line"), "path": r.get("path_pattern")}
                if h_entry not in ext_handlers:
                    ext_handlers.append(h_entry)
            http_calls.append({"method": c_method, "url": c_url, "line": c.get("line_number"), "external_handlers": ext_handlers})
        return route_meta, ext_callers, http_calls

    return resolve_http_boundaries
