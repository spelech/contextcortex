import json
import sys
from collections import deque
from typing import Dict, List, Optional, Set, Tuple

from app.services.chunking.route_specificity import call_belongs_to_route, is_test_route_file
from app.services.database import get_db_connection
from app.services.git_manager import format_git_permalink
from app.services.source_paths import LocalSourceRoots

_DIRECTION_ALIASES = {
    "inbound": "callers",
    "outbound": "callees",
    "callers": "callers",
    "callees": "callees",
    "both": "both",
}

_CONTAINER_KINDS = frozenset({
    "class_declaration", "class_definition", "interface_declaration",
    "struct_declaration", "record_declaration", "record_struct_declaration",
    "namespace_definition", "program_definition",
})


def _db_conn():
    search_mod = sys.modules.get("app.services.search")
    fn = getattr(search_mod, "get_db_connection", None) if search_mod else None
    return (fn or get_db_connection)()


def _fmt_permalink(url: str, sha: Optional[str], rel_path: str, start_l: Optional[int], end_l: Optional[int], provider: Optional[str] = None) -> Optional[str]:
    search_mod = sys.modules.get("app.services.search")
    fn = getattr(search_mod, "format_git_permalink", None) if search_mod else None
    return (fn or format_git_permalink)(url, sha, rel_path, start_l, end_l, provider=provider)


def _clean_path(filepath: Optional[str]) -> str:
    if not filepath:
        return ""
    fp = filepath.replace("\\", "/")
    return fp.split("://", 1)[1] if "://" in fp else fp


def _methods_compatible(m1: Optional[str], m2: Optional[str]) -> bool:
    if not m1 or not m2:
        return True
    u1, u2 = m1.upper(), m2.upper()
    return u1 == "ALL" or u2 == "ALL" or u1 == u2


def trace_symbol_path(
    symbol: str,
    repo: Optional[str] = None,
    direction: str = "both",
    depth: int = 2,
    limit: int = 25,
) -> str:
    """
    Breadth-First Search (BFS) call graph traversal engine over ast_relationships.
    Supports direction ('callers'/'inbound', 'callees'/'outbound', 'both'), depth clamping (1-5),
    cross-repository HTTP boundaries, COBOL program/paragraph/copybook links, and DI interface resolution.
    """
    target_sym = symbol.strip() if symbol else ""
    if not target_sym:
        return json.dumps({"error": "Target symbol cannot be empty."}, separators=(",", ":"))

    direction = _DIRECTION_ALIASES.get((direction or "both").lower().strip(), "both")
    depth = max(1, min(5, depth))
    limit = max(1, limit)
    short_target = target_sym.split(".")[-1] if "." in target_sym else target_sym

    with _db_conn() as conn:
        repo_sql = " AND repo = ?" if repo else ""
        repo_arg = [repo] if repo else []
        sym_query = (
            "SELECT id, repo, filepath, name, full_symbol, kind, start_line, end_line, signature "
            "FROM ast_symbols WHERE (name = ? OR full_symbol = ? OR full_symbol LIKE ?)"
            + repo_sql
            + " ORDER BY (CASE WHEN full_symbol = ? THEN 1 WHEN name = ? THEN 2 ELSE 3 END)"
        )
        symbols_found = conn.execute(sym_query, [target_sym, target_sym, f"%.{target_sym}"] + repo_arg + [target_sym, target_sym]).fetchall()

        if not symbols_found:
            nc_query = (
                "SELECT id, repo, filepath, name, full_symbol, kind, start_line, end_line, signature "
                "FROM ast_symbols WHERE (LOWER(name) = LOWER(?) OR LOWER(full_symbol) = LOWER(?) OR LOWER(full_symbol) LIKE LOWER(?))"
                + repo_sql
            )
            symbols_found = conn.execute(nc_query, [target_sym, target_sym, f"%.{target_sym}"] + repo_arg).fetchall()
            if symbols_found:
                s0m = symbols_found[0]
                if "." in target_sym and s0m["full_symbol"]:
                    target_sym = s0m["full_symbol"]
                elif s0m["name"] and s0m["name"].upper() == target_sym.upper():
                    target_sym = s0m["name"]
                elif s0m["full_symbol"]:
                    target_sym = s0m["full_symbol"]
                short_target = target_sym.split(".")[-1] if "." in target_sym else target_sym

        if not symbols_found:
            rel_hit = conn.execute(
                "SELECT source_symbol, target_symbol FROM ast_relationships "
                "WHERE (source_symbol = ? OR target_symbol = ? OR source_symbol = ? OR target_symbol = ?)"
                + repo_sql + " LIMIT 1",
                [target_sym, target_sym, short_target, short_target] + repo_arg,
            ).fetchone()
            if not rel_hit:
                rel_hit = conn.execute(
                    "SELECT source_symbol, target_symbol FROM ast_relationships "
                    "WHERE (LOWER(source_symbol) = LOWER(?) OR LOWER(target_symbol) = LOWER(?))"
                    + repo_sql + " LIMIT 1",
                    [target_sym, target_sym] + repo_arg,
                ).fetchone()
                if rel_hit:
                    target_sym = rel_hit["source_symbol"] if (rel_hit["source_symbol"] or "").upper() == target_sym.upper() else rel_hit["target_symbol"]
                    short_target = target_sym.split(".")[-1] if "." in target_sym else target_sym
            if not rel_hit:
                return json.dumps({"symbol": target_sym, "found": False, "callers": [], "callees": []}, separators=(",", ":"))

        git_repos = {r["name"]: dict(r) for r in conn.execute("SELECT name, url, commit_sha, provider FROM git_repositories").fetchall()}
        all_routes = [dict(r) for r in conn.execute("SELECT id, repo, filepath, framework, http_method, path_pattern, handler_symbol, start_line, end_line FROM api_routes").fetchall()]
        all_calls = [dict(c) for c in conn.execute("SELECT id, repo, filepath, http_method, url_pattern, caller_symbol, line_number FROM api_client_calls").fetchall()]
        _rel_path = LocalSourceRoots.load(conn).relative

    def get_permalink(r_repo: str, r_filepath: str, start_l: Optional[int], end_l: Optional[int]) -> Optional[str]:
        g_info = git_repos.get(r_repo)
        return _fmt_permalink(g_info["url"], g_info["commit_sha"], _rel_path(r_filepath), start_l, end_l, provider=g_info.get("provider")) if g_info else None

    bfs_repo = repo or (symbols_found[0]["repo"] if symbols_found else None)
    bfs_clause = " WHERE repo = ?" if bfs_repo else ""
    bfs_args = (bfs_repo,) if bfs_repo else ()

    with _db_conn() as conn:
        repo_symbols = [
            dict(r) for r in conn.execute(
                "SELECT id, repo, filepath, name, full_symbol, kind, start_line, end_line, signature FROM ast_symbols" + bfs_clause,
                bfs_args,
            ).fetchall()
        ]
        impl_rows = conn.execute(
            "SELECT source_symbol, source_filepath, target_symbol FROM ast_relationships WHERE relationship_type = 'IMPLEMENTS'" + (" AND repo = ?" if bfs_repo else ""),
            bfs_args,
        ).fetchall()

    sym_by_id: Dict[int, dict] = {s["id"]: s for s in repo_symbols if s.get("id") is not None}
    syms_by_full: Dict[str, List[dict]] = {}
    syms_by_name: Dict[str, List[dict]] = {}
    syms_by_full_upper: Dict[str, List[dict]] = {}
    syms_by_name_upper: Dict[str, List[dict]] = {}
    syms_by_file: Dict[Tuple[Optional[str], str], List[dict]] = {}
    interface_names: Set[str] = set()
    class_signatures: Dict[str, str] = {}

    for s in repo_symbols:
        s["_clean_fp"] = _rel_path(s.get("filepath"))
        s["_test"] = is_test_route_file(s["_clean_fp"])
        full_s, name_s = s.get("full_symbol"), s.get("name")
        if full_s:
            syms_by_full.setdefault(full_s, []).append(s)
            syms_by_full_upper.setdefault(full_s.upper(), []).append(s)
        if name_s:
            syms_by_name.setdefault(name_s, []).append(s)
            syms_by_name_upper.setdefault(name_s.upper(), []).append(s)
        syms_by_file.setdefault((s.get("repo"), s["_clean_fp"]), []).append(s)
        if s.get("kind") == "interface_declaration" and name_s:
            interface_names.add(name_s)
            if full_s:
                interface_names.add(full_s)
        if s.get("signature"):
            owner = full_s.split(".")[0] if full_s and "." in full_s else (name_s or "")
            if owner:
                class_signatures[owner] = class_signatures.get(owner, "") + " " + s["signature"]

    concrete_to_ifaces: Dict[str, Set[str]] = {}
    iface_to_concretes: Dict[str, Set[str]] = {}
    for ir in impl_rows:
        src_cls = (ir["source_symbol"] or "").split(".")[-1]
        tgt_iface = (ir["target_symbol"] or "").split(".")[-1]
        if src_cls and tgt_iface:
            concrete_to_ifaces.setdefault(src_cls, set()).add(tgt_iface)
            # Test doubles do not count as implementations: one real class plus fakes is still one implementation.
            if not is_test_route_file(_rel_path(ir["source_filepath"])):
                iface_to_concretes.setdefault(tgt_iface, set()).add(src_cls)

    def _resolve_symbol_candidates(sym_str: str) -> List[dict]:
        if not sym_str:
            return []
        exact = syms_by_full.get(sym_str) or syms_by_name.get(sym_str)
        if exact:
            return exact
        suffix = [s for fk, lst in syms_by_full.items() if fk.endswith(f".{sym_str}") for s in lst]
        if suffix:
            return suffix
        up = sym_str.upper()
        return syms_by_full_upper.get(up) or syms_by_name_upper.get(up) or []

    def _single_implementation(full: str) -> str:
        """`IRepo.Save` -> `SqlRepo.Save` when exactly one class implements `IRepo` and has the member."""
        if "." not in full:
            return full
        owner, member = full.rsplit(".", 1)
        impls = iface_to_concretes.get(owner.split(".")[-1], set())
        if len(impls) == 1:
            impl_cands = syms_by_full.get(f"{next(iter(impls))}.{member}", [])
            if impl_cands:
                return impl_cands[0]["full_symbol"]
        return full

    def _resolve_di_callee(raw_target: str, caller_sym: str, candidates: List[dict], caller_file: Optional[str] = None) -> str:
        if caller_file and candidates and not is_test_route_file(_rel_path(caller_file)):
            # Production code never calls into test code: drop test candidates, and keep the call unresolved
            # when only test candidates match (for example `transaction.Commit()` and a fake transaction class).
            candidates = [c for c in candidates if not c.get("_test")]
            if not candidates:
                return raw_target
        if not candidates:
            if "." in raw_target:
                owner, member = raw_target.rsplit(".", 1)
                impls = iface_to_concretes.get(owner, set())
                if len(impls) == 1:
                    impl_cands = syms_by_full.get(f"{next(iter(impls))}.{member}", [])
                    if impl_cands:
                        return impl_cands[0]["full_symbol"]
            return raw_target
        if len(candidates) == 1:
            return _single_implementation(candidates[0].get("full_symbol") or candidates[0].get("name") or raw_target)
        non_iface = [
            c for c in candidates
            if (c.get("full_symbol") or "").rsplit(".", 1)[0] not in interface_names and c.get("kind") != "interface_declaration"
        ]
        pool = non_iface or candidates
        if len(pool) == 1:
            return pool[0].get("full_symbol") or pool[0].get("name") or raw_target
        caller_cls = caller_sym.split(".")[0] if "." in caller_sym else caller_sym
        sig_blob = class_signatures.get(caller_cls, "")
        if sig_blob:
            matched = [
                c for c in pool
                if any(iface in sig_blob for iface in concrete_to_ifaces.get((c.get("full_symbol") or "").rsplit(".", 1)[0], ()))
            ]
            if len(matched) == 1:
                return matched[0].get("full_symbol") or matched[0].get("name") or raw_target
        return raw_target

    def _call_reaches(r_target: str, caller_sym: str, curr_sym: str) -> bool:
        """
        Call targets are stored as bare method names (`_toolService.PublishInstance(...)` -> `PublishInstance`).
        For a qualified target, resolve the call from the caller's class with the same DI rules as callees:
        when it resolves to a different concrete method, the row is not a caller of `curr_sym`.
        Calls from the target's own class, and undecidable calls, are kept.
        """
        if "." not in curr_sym or not r_target or "." in r_target:
            return True
        curr_cls = curr_sym.rsplit(".", 1)[0]
        caller_cls = caller_sym.rsplit(".", 1)[0] if "." in caller_sym else caller_sym
        if caller_cls == curr_cls or caller_cls.endswith(f".{curr_cls}"):
            return True
        candidates = _resolve_symbol_candidates(r_target)
        if len(candidates) < 2:
            return True
        resolved = _resolve_di_callee(r_target, caller_sym, candidates)
        return resolved == r_target or resolved == curr_sym or resolved.endswith(f".{curr_sym}")

    def _resolve_enclosing_symbol(r_repo: str, r_filepath: str, line_num: Optional[int], fallback_sym: str, source_symbol_id: Optional[int] = None) -> Tuple[str, Optional[dict]]:
        if source_symbol_id and source_symbol_id in sym_by_id:
            s_obj = sym_by_id[source_symbol_id]
            return (s_obj.get("full_symbol") or s_obj.get("name") or fallback_sym), s_obj
        file_syms = syms_by_file.get((r_repo, _rel_path(r_filepath)), [])
        if line_num is not None and file_syms:
            enclosing = [
                s for s in file_syms
                if (s.get("start_line") or 0) <= line_num <= (s.get("end_line") or 0) and s.get("kind") not in _CONTAINER_KINDS
            ]
            if enclosing:
                enclosing.sort(key=lambda s: (s.get("end_line") or 0) - (s.get("start_line") or 0))
                best = enclosing[0]
                return (best.get("full_symbol") or best.get("name") or fallback_sym), best
        for s in file_syms:
            if s.get("name") == fallback_sym or s.get("full_symbol") == fallback_sym:
                return (s.get("full_symbol") or s.get("name") or fallback_sym), s
        return fallback_sym, None

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

    if symbols_found:
        s0 = symbols_found[0]
        s_file = _rel_path(s0["filepath"])
        target_info = {
            "symbol": s0["full_symbol"] or s0["name"], "name": s0["name"], "kind": s0["kind"],
            "repo": s0["repo"], "file": s_file,
            "lines": [s0["start_line"], s0["end_line"]] if s0["start_line"] is not None and s0["end_line"] is not None else [],
            "permalink": get_permalink(s0["repo"], s_file, s0["start_line"], s0["end_line"]),
        }
    else:
        with _db_conn() as conn:
            r_filter = "AND repo = ? " if bfs_repo else ""
            r_args = [target_sym, bfs_repo] if bfs_repo else [target_sym]
            row = conn.execute(f"SELECT repo, source_filepath, line_number FROM ast_relationships WHERE source_symbol = ? {r_filter}LIMIT 1", r_args).fetchone()
            if not row:
                row = conn.execute(f"SELECT repo, source_filepath, line_number FROM ast_relationships WHERE target_symbol = ? {r_filter}LIMIT 1", r_args).fetchone()
        t_repo = row["repo"] if row else (bfs_repo or "")
        t_file = _rel_path(row["source_filepath"]) if row else ""
        t_line = row["line_number"] if row else 1
        target_info = {
            "symbol": target_sym, "name": target_sym.split(".")[-1], "kind": "function",
            "repo": t_repo, "file": t_file, "lines": [t_line, t_line] if row else [],
            "permalink": get_permalink(t_repo, t_file, t_line, t_line) if row else None,
        }

    t_route, t_callers, t_http_calls = resolve_http_boundaries(target_sym, target_info.get("repo", ""))
    if t_route:
        target_info["route"] = t_route
    if t_callers:
        target_info["external_callers"] = t_callers
    if t_http_calls:
        target_info["http_calls"] = t_http_calls

    def _make_edge_node(display_sym: str, row_obj: object, child_key: str) -> dict:
        clean_fp = _rel_path(row_obj["source_filepath"])
        r_route, r_ext_callers, r_http_calls = resolve_http_boundaries(display_sym, row_obj["repo"])
        node = {
            "symbol": display_sym,
            "rel": (row_obj["relationship_type"] or "calls").lower(),
            "repo": row_obj["repo"],
            "file": clean_fp,
            "line": row_obj["line_number"],
            "permalink": get_permalink(row_obj["repo"], clean_fp, row_obj["line_number"], row_obj["line_number"]),
        }
        if r_route:
            node["route"] = r_route
        if r_ext_callers:
            node["external_callers"] = r_ext_callers
        if r_http_calls:
            node["http_calls"] = r_http_calls
        node[child_key] = []
        return node

    visited_edges = set()
    total_returned = 0
    truncated = False
    callers_tree: List[dict] = []
    callees_tree: List[dict] = []

    with _db_conn() as conn:
        if direction in ("callers", "both"):
            queue = deque([(target_sym, 1, callers_tree)])
            visited_nodes = {target_sym}
            while queue:
                curr_sym, curr_depth, parent_list = queue.popleft()
                if curr_depth > depth:
                    continue
                short_curr = curr_sym.split(".")[-1] if "." in curr_sym else curr_sym
                curr_ids = {c["id"] for c in _resolve_symbol_candidates(curr_sym) if c.get("id") is not None}
                curr_ifaces = concrete_to_ifaces.get(curr_sym.rsplit(".", 1)[0] if "." in curr_sym else "", set())

                q = "SELECT repo, source_symbol_id, source_filepath, source_symbol, target_symbol, relationship_type, line_number FROM ast_relationships WHERE (target_symbol = ? OR target_symbol = ? OR target_symbol LIKE ?)"
                p: List[object] = [curr_sym, short_curr, f"%.{short_curr}"]
                if bfs_repo:
                    q += " AND repo = ?"
                    p.append(bfs_repo)
                rows = conn.execute(q + " ORDER BY line_number ASC", p).fetchall()

                for r in rows:
                    if total_returned >= limit:
                        truncated = True
                        break
                    r_target = r["target_symbol"] or ""
                    if "." in curr_sym and "." in r_target and r_target != curr_sym and not r_target.endswith(f".{curr_sym}") and not curr_sym.endswith(f".{r_target}"):
                        if r_target.rsplit(".", 1)[0] not in curr_ifaces:
                            continue
                    caller_sym, caller_obj = _resolve_enclosing_symbol(r["repo"], r["source_filepath"], r["line_number"], r["source_symbol"], r["source_symbol_id"])
                    if (caller_obj and caller_obj.get("id") in curr_ids and "." in curr_sym) or caller_sym == curr_sym:
                        continue
                    if not _call_reaches(r_target, caller_sym, curr_sym):
                        continue
                    edge_key = (caller_sym, curr_sym, r["relationship_type"], "caller", r["line_number"])
                    if edge_key in visited_edges:
                        continue
                    visited_edges.add(edge_key)
                    total_returned += 1
                    node = _make_edge_node(caller_sym, r, "callers")
                    parent_list.append(node)
                    if curr_depth < depth and caller_sym not in visited_nodes:
                        visited_nodes.add(caller_sym)
                        if total_returned < limit:
                            queue.append((caller_sym, curr_depth + 1, node["callers"]))
                        else:
                            truncated = True

        if direction in ("callees", "both"):
            queue = deque([(target_sym, 1, callees_tree)])
            visited_nodes = {target_sym}
            while queue:
                curr_sym, curr_depth, parent_list = queue.popleft()
                if curr_depth > depth:
                    continue
                short_curr = curr_sym.split(".")[-1] if "." in curr_sym else curr_sym
                curr_candidates = _resolve_symbol_candidates(curr_sym)
                curr_ids_list = [c["id"] for c in curr_candidates if c.get("id") is not None]
                for c in curr_candidates:
                    if c.get("kind") == "program_definition" and c.get("name"):
                        prog_prefix = f"{c['name']}."
                        for s in repo_symbols:
                            if (s.get("full_symbol") or "").startswith(prog_prefix) and s.get("id") is not None and s["id"] not in curr_ids_list:
                                curr_ids_list.append(s["id"])

                q = "SELECT repo, source_symbol_id, source_filepath, source_symbol, target_symbol, relationship_type, line_number FROM ast_relationships WHERE (source_symbol = ? OR source_symbol = ?"
                p = [curr_sym, short_curr]
                if curr_ids_list:
                    q += f" OR source_symbol_id IN ({','.join('?' for _ in curr_ids_list)})"
                    p.extend(curr_ids_list)
                q += ")"
                if bfs_repo:
                    q += " AND repo = ?"
                    p.append(bfs_repo)
                rows = conn.execute(q + " ORDER BY line_number ASC", p).fetchall()

                for r in rows:
                    if total_returned >= limit:
                        truncated = True
                        break
                    caller_sym = curr_sym
                    if "." in curr_sym and curr_candidates:
                        caller_sym, _ = _resolve_enclosing_symbol(r["repo"], r["source_filepath"], r["line_number"], r["source_symbol"], r["source_symbol_id"])
                        if caller_sym != curr_sym and not caller_sym.endswith(f".{curr_sym}"):
                            continue
                    raw_target = r["target_symbol"]
                    callee_cands = [c for c in _resolve_symbol_candidates(raw_target) if c.get("full_symbol") != curr_sym]
                    callee_sym = _resolve_di_callee(raw_target, caller_sym, callee_cands, r["source_filepath"])
                    edge_key = (curr_sym, callee_sym, r["relationship_type"], "callee", r["line_number"])
                    if edge_key in visited_edges:
                        continue
                    visited_edges.add(edge_key)
                    total_returned += 1
                    node = _make_edge_node(callee_sym, r, "callees")
                    parent_list.append(node)
                    if curr_depth < depth and callee_sym not in visited_nodes:
                        visited_nodes.add(callee_sym)
                        if total_returned < limit:
                            queue.append((callee_sym, curr_depth + 1, node["callees"]))
                        else:
                            truncated = True

    return json.dumps({
        "target": target_info, "direction": direction, "depth": depth,
        "truncated": truncated, "callers": callers_tree, "callees": callees_tree,
    }, separators=(",", ":"))
