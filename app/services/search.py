import logging
from typing import Optional, List
from app.services.vector_store import get_vector_store, VectorSearchResult

logger = logging.getLogger('contextcortex.search')


import json
from collections import deque
from app.services.database import get_db_connection
from app.services.git_manager import format_git_permalink
from app.services.chunking import match_route_and_call

def _clean_path(filepath: Optional[str]) -> str:
    if not filepath:
        return ""
    if "://" in filepath:
        return filepath.split("://", 1)[1]
    return filepath

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
    limit: int = 25
) -> str:
    """
    Breadth-First Search (BFS) call graph traversal engine over ast_relationships.
    Supports direction ('callers', 'callees', 'both'), depth clamping (1-5), and total limit pagination.
    Resolves cross-repository HTTP boundaries (api_routes <-> api_client_calls).
    Returns deterministic, compact JSON string.
    """
    target_sym = symbol.strip() if symbol else ""
    if not target_sym:
        return json.dumps({"error": "Target symbol cannot be empty."}, separators=(",", ":"))

    direction = (direction or "both").lower().strip()
    if direction not in ("callers", "callees", "both"):
        direction = "both"

    depth = max(1, min(5, depth))
    limit = max(1, limit)

    with get_db_connection() as conn:
        # Check if symbol exists in symbols or relationships
        sym_query = "SELECT id, repo, filepath, name, full_symbol, kind, start_line, end_line FROM ast_symbols WHERE name = ? OR full_symbol = ?"
        sym_params = [target_sym, target_sym]
        if repo:
            sym_query += " AND repo = ?"
            sym_params.append(repo)

        symbols_found = conn.execute(sym_query, sym_params).fetchall()

        # If no exact symbol found in ast_symbols, check ast_relationships
        if not symbols_found:
            rel_check = conn.execute(
                "SELECT count(*) FROM ast_relationships WHERE (source_symbol = ? OR target_symbol = ?)" + (" AND repo = ?" if repo else ""),
                [target_sym, target_sym, repo] if repo else [target_sym, target_sym]
            ).fetchone()[0]
            if rel_check == 0:
                return json.dumps({"symbol": target_sym, "found": False, "callers": [], "callees": []}, separators=(",", ":"))

        # Fetch git repository info for permalink formatting
        git_repos = {}
        for r in conn.execute("SELECT name, url, commit_sha, provider FROM git_repositories").fetchall():
            git_repos[r["name"]] = dict(r)

        # Pre-load all routes and client calls across all repos to resolve boundaries efficiently
        all_routes = [dict(r) for r in conn.execute("SELECT id, repo, filepath, framework, http_method, path_pattern, handler_symbol, start_line, end_line FROM api_routes").fetchall()]
        all_calls = [dict(c) for c in conn.execute("SELECT id, repo, filepath, http_method, url_pattern, caller_symbol, line_number FROM api_client_calls").fetchall()]

    def get_permalink(r_repo: str, r_filepath: str, start_l: Optional[int], end_l: Optional[int]) -> Optional[str]:
        g_info = git_repos.get(r_repo)
        if not g_info:
            return None
        rel_path = _clean_path(r_filepath)
        return format_git_permalink(
            g_info["url"],
            g_info["commit_sha"],
            rel_path,
            start_l,
            end_l,
            provider=g_info.get("provider")
        )

    # Scoped repository determination: if repo is passed, scope BFS to it;
    # otherwise if symbols_found, scope BFS to symbol's repo
    bfs_repo = repo
    if not bfs_repo and symbols_found:
        bfs_repo = symbols_found[0]["repo"]

    # Target info
    target_info = None
    if symbols_found:
        s0 = symbols_found[0]
        s_repo = s0["repo"]
        s_file = _clean_path(s0["filepath"])
        plink = get_permalink(s_repo, s_file, s0["start_line"], s0["end_line"])
        target_info = {
            "symbol": s0["full_symbol"] or s0["name"],
            "name": s0["name"],
            "kind": s0["kind"],
            "repo": s_repo,
            "file": s_file,
            "lines": [s0["start_line"], s0["end_line"]] if s0["start_line"] is not None and s0["end_line"] is not None else [],
            "permalink": plink
        }
    else:
        # Construct fallback target_info from ast_relationships if possible
        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT repo, source_filepath, line_number FROM ast_relationships WHERE source_symbol = ? " + ("AND repo = ? " if bfs_repo else "") + "LIMIT 1",
                [target_sym, bfs_repo] if bfs_repo else [target_sym]
            ).fetchone()
            if not row:
                row = conn.execute(
                    "SELECT repo, source_filepath, line_number FROM ast_relationships WHERE target_symbol = ? " + ("AND repo = ? " if bfs_repo else "") + "LIMIT 1",
                    [target_sym, bfs_repo] if bfs_repo else [target_sym]
                ).fetchone()

        t_repo = row["repo"] if row else (bfs_repo or "")
        t_file = _clean_path(row["source_filepath"]) if row else ""
        t_line = row["line_number"] if row else 1
        plink = get_permalink(t_repo, t_file, t_line, t_line) if row else None
        target_info = {
            "symbol": target_sym,
            "name": target_sym.split(".")[-1],
            "kind": "function",
            "repo": t_repo,
            "file": t_file,
            "lines": [t_line, t_line] if row else [],
            "permalink": plink
        }

    # Helper function to resolve cross-repo HTTP boundaries for a given symbol
    def resolve_http_boundaries(sym_name: str, sym_repo: str):
        """
        Returns (route_dict_or_None, external_callers_list, http_calls_list)
        """
        route_meta = None
        ext_callers = []
        http_calls = []

        # 1. Inbound Route Match (api_routes -> api_client_calls)
        # Check if sym is a route handler
        matched_routes = [
            r for r in all_routes
            if (r.get("repo") == sym_repo or not sym_repo) and
               (r.get("handler_symbol") == sym_name or (r.get("handler_symbol") and (r["handler_symbol"] == sym_name.split(".")[-1] or sym_name.endswith(f".{r['handler_symbol']}"))))
        ]

        if matched_routes:
            # Attach route info
            primary_route = matched_routes[0]
            route_meta = {
                "method": primary_route["http_method"].upper(),
                "path": primary_route["path_pattern"]
            }

            # Find external callers across all indexed repositories
            for r_item in matched_routes:
                r_method = r_item["http_method"]
                r_pattern = r_item["path_pattern"]
                for c in all_calls:
                    # Ignore internal callers from the same repo if looking for external callers,
                    # but spec says: "matching cross-repo HTTP callers (external_callers)"
                    if c["repo"] == sym_repo:
                        continue
                    if _methods_compatible(r_method, c.get("http_method")) and match_route_and_call(r_pattern, c.get("url_pattern", "")):
                        c_file = _clean_path(c["filepath"])
                        caller_entry = {
                            "repo": c["repo"],
                            "symbol": c.get("caller_symbol") or "",
                            "file": c_file,
                            "line": c.get("line_number"),
                            "method": c.get("http_method", "").upper(),
                            "url": c.get("url_pattern", "")
                        }
                        if caller_entry not in ext_callers:
                            ext_callers.append(caller_entry)

        # 2. Outbound HTTP Call Match (api_client_calls -> api_routes)
        # Check if sym makes outbound HTTP calls
        matched_calls = [
            c for c in all_calls
            if (c.get("repo") == sym_repo or not sym_repo) and
               (c.get("caller_symbol") == sym_name or (c.get("caller_symbol") and (c["caller_symbol"] == sym_name.split(".")[-1] or sym_name.endswith(f".{c['caller_symbol']}"))))
        ]

        if matched_calls:
            # Group by outbound call site
            for c in matched_calls:
                c_method = c.get("http_method", "").upper()
                c_url = c.get("url_pattern", "")
                c_line = c.get("line_number")

                ext_handlers = []
                for r in all_routes:
                    if r["repo"] == sym_repo:
                        continue
                    if _methods_compatible(r.get("http_method"), c_method) and match_route_and_call(r.get("path_pattern", ""), c_url):
                        r_file = _clean_path(r["filepath"])
                        handler_entry = {
                            "repo": r["repo"],
                            "symbol": r.get("handler_symbol") or "",
                            "file": r_file,
                            "line": r.get("start_line"),
                            "path": r.get("path_pattern")
                        }
                        if handler_entry not in ext_handlers:
                            ext_handlers.append(handler_entry)

                call_site_entry = {
                    "method": c_method,
                    "url": c_url,
                    "line": c_line,
                    "external_handlers": ext_handlers
                }
                http_calls.append(call_site_entry)

        return route_meta, ext_callers, http_calls

    # Attach HTTP boundaries to target_info if applicable
    t_route, t_callers, t_http_calls = resolve_http_boundaries(target_sym, target_info.get("repo", ""))
    if t_route:
        target_info["route"] = t_route
    if t_callers:
        target_info["external_callers"] = t_callers
    if t_http_calls:
        target_info["http_calls"] = t_http_calls

    visited_edges = set()
    total_returned = 0
    truncated = False

    with get_db_connection() as conn:
        # Build inbound (callers) sub-tree
        callers_tree = []
        if direction in ("callers", "both"):
            queue = deque([(target_sym, 1, callers_tree)])
            visited_nodes = {target_sym}

            while queue:
                curr_sym, curr_depth, parent_list = queue.popleft()
                if curr_depth > depth:
                    continue

                query = """
                    SELECT r.repo, r.source_filepath, r.source_symbol, r.target_symbol, r.relationship_type, r.line_number, s.start_line, s.end_line
                    FROM ast_relationships r
                    LEFT JOIN ast_symbols s ON r.source_symbol_id = s.id
                    WHERE r.target_symbol = ?
                """
                params = [curr_sym]
                if bfs_repo:
                    query += " AND r.repo = ?"
                    params.append(bfs_repo)
                query += " ORDER BY r.line_number ASC"

                rows = conn.execute(query, params).fetchall()

                for r in rows:
                    if total_returned >= limit:
                        truncated = True
                        break

                    edge_key = (r["source_symbol"], curr_sym, r["relationship_type"], "caller")
                    if edge_key in visited_edges:
                        continue
                    visited_edges.add(edge_key)

                    total_returned += 1
                    clean_fp = _clean_path(r["source_filepath"])
                    plink = get_permalink(r["repo"], clean_fp, r["line_number"], r["line_number"])

                    r_route, r_ext_callers, r_http_calls = resolve_http_boundaries(r["source_symbol"], r["repo"])

                    rel_label = (r["relationship_type"] or "calls").lower()

                    node = {
                        "symbol": r["source_symbol"],
                        "rel": rel_label,
                        "repo": r["repo"],
                        "file": clean_fp,
                        "line": r["line_number"],
                        "permalink": plink
                    }
                    if r_route:
                        node["route"] = r_route
                    if r_ext_callers:
                        node["external_callers"] = r_ext_callers
                    if r_http_calls:
                        node["http_calls"] = r_http_calls

                    node["callers"] = []
                    parent_list.append(node)

                    if curr_depth < depth and r["source_symbol"] not in visited_nodes:
                        visited_nodes.add(r["source_symbol"])
                        if total_returned < limit:
                            queue.append((r["source_symbol"], curr_depth + 1, node["callers"]))
                        else:
                            truncated = True

        # Build outbound (callees) sub-tree
        callees_tree = []
        if direction in ("callees", "both"):
            queue = deque([(target_sym, 1, callees_tree)])
            visited_nodes = {target_sym}

            while queue:
                curr_sym, curr_depth, parent_list = queue.popleft()
                if curr_depth > depth:
                    continue

                query = """
                    SELECT r.repo, r.source_filepath, r.source_symbol, r.target_symbol, r.relationship_type, r.line_number, s.start_line, s.end_line
                    FROM ast_relationships r
                    LEFT JOIN ast_symbols s ON r.source_symbol_id = s.id
                    WHERE r.source_symbol = ?
                """
                params = [curr_sym]
                if bfs_repo:
                    query += " AND r.repo = ?"
                    params.append(bfs_repo)
                query += " ORDER BY r.line_number ASC"

                rows = conn.execute(query, params).fetchall()

                for r in rows:
                    if total_returned >= limit:
                        truncated = True
                        break

                    edge_key = (curr_sym, r["target_symbol"], r["relationship_type"], "callee")
                    if edge_key in visited_edges:
                        continue
                    visited_edges.add(edge_key)

                    total_returned += 1
                    clean_fp = _clean_path(r["source_filepath"])
                    plink = get_permalink(r["repo"], clean_fp, r["line_number"], r["line_number"])

                    r_route, r_ext_callers, r_http_calls = resolve_http_boundaries(r["target_symbol"], r["repo"])

                    rel_label = (r["relationship_type"] or "calls").lower()

                    node = {
                        "symbol": r["target_symbol"],
                        "rel": rel_label,
                        "repo": r["repo"],
                        "file": clean_fp,
                        "line": r["line_number"],
                        "permalink": plink
                    }
                    if r_route:
                        node["route"] = r_route
                    if r_ext_callers:
                        node["external_callers"] = r_ext_callers
                    if r_http_calls:
                        node["http_calls"] = r_http_calls

                    node["callees"] = []
                    parent_list.append(node)

                    if curr_depth < depth and r["target_symbol"] not in visited_nodes:
                        visited_nodes.add(r["target_symbol"])
                        if total_returned < limit:
                            queue.append((r["target_symbol"], curr_depth + 1, node["callees"]))
                        else:
                            truncated = True

    payload = {
        "target": target_info,
        "direction": direction,
        "depth": depth,
        "truncated": truncated,
        "callers": callers_tree,
        "callees": callees_tree
    }

    return json.dumps(payload, separators=(",", ":"))


def _enrich_code_ast_metadata(results: List[VectorSearchResult]) -> None:
    """Enriches code hits with AST symbol details (signature, clean kind, ast_symbol_id)."""
    if not results:
        return

    code_results = [r for r in results if r.payload.get("doc_type") == "code" or r.payload.get("symbol")]
    if not code_results:
        return

    try:
        with get_db_connection() as conn:
            for r in code_results:
                p = r.payload
                repo = p.get("repo")
                rel_path = p.get("rel_path") or p.get("path")
                sym_name = p.get("symbol")
                start_l = p.get("start_line")
                end_l = p.get("end_line")

                clean_fp = rel_path.lstrip("/").replace("\\", "/") if rel_path else ""

                row = None
                # Priority 1: match by exact symbol and repo and filepath/lines
                if sym_name and repo:
                    member_name = sym_name.split(".")[-1]
                    row = conn.execute(
                        """
                        SELECT id, name, full_symbol, kind, signature, start_line, end_line
                        FROM ast_symbols
                        WHERE repo = ? 
                          AND (name = ? OR full_symbol = ? OR name = ?)
                          AND (filepath = ? OR filepath = ? OR filepath LIKE ?)
                        ORDER BY (CASE WHEN full_symbol = ? THEN 1 WHEN name = ? THEN 2 ELSE 3 END),
                                 abs(start_line - ?) ASC
                        LIMIT 1
                        """,
                        (repo, sym_name, sym_name, member_name, clean_fp, f"/{clean_fp}", f"%/{clean_fp}", sym_name, member_name, start_l or 0)
                    ).fetchone()

                # Priority 2: match by file and overlapping line span if not found
                if not row and repo and clean_fp and start_l is not None and end_l is not None:
                    row = conn.execute(
                        """
                        SELECT id, name, full_symbol, kind, signature, start_line, end_line
                        FROM ast_symbols
                        WHERE repo = ?
                          AND (filepath = ? OR filepath = ? OR filepath LIKE ?)
                          AND start_line <= ? AND end_line >= ?
                        ORDER BY (end_line - start_line) ASC
                        LIMIT 1
                        """,
                        (repo, clean_fp, f"/{clean_fp}", f"%/{clean_fp}", end_l, start_l)
                    ).fetchone()

                if row:
                    if row["signature"] and not p.get("signature"):
                        p["signature"] = row["signature"]
                    if row["full_symbol"] and not p.get("full_symbol"):
                        p["full_symbol"] = row["full_symbol"]
                    if row["kind"] and (not p.get("kind") or p.get("kind") == "module"):
                        p["kind"] = row["kind"]
                    if "ast_symbol_id" not in p and row["id"]:
                        p["ast_symbol_id"] = row["id"]
    except Exception as e:
        logger.debug(f"AST enrichment skipped due to error: {e}")


def execute_hybrid_search(
    query_text: str,
    doc_type: Optional[str] = None,
    repo: Optional[str] = None,
    language: Optional[str] = None,
    category: Optional[str] = None,
    tag: Optional[str] = None,
    limit: int = 5,
    dense_weight: Optional[float] = None,
    search_mode: str = "hybrid"
) -> List[VectorSearchResult]:
    """Executes vector search via the configured active VectorStore backend and enriches code hits with AST metadata."""
    if not query_text or not query_text.strip():
        return []

    try:
        store = get_vector_store()
        try:
            caps = store.get_capabilities()
            if isinstance(caps, dict):
                supported = caps.get("search_modes", ["hybrid", "semantic", "lexical"])
            else:
                supported = ["hybrid", "semantic", "lexical"]
        except Exception:
            supported = ["hybrid", "semantic", "lexical"]

        mode = (search_mode or "hybrid").lower().strip()
        if mode not in supported:
            if mode == "hybrid" and "semantic" in supported:
                mode = "semantic"
            else:
                raise ValueError(
                    f"Search mode '{search_mode}' is not supported by the active vector store backend ({store.__class__.__name__}). Supported modes: {supported}"
                )

        results = store.search(
            query_text=query_text.strip(),
            doc_type=doc_type,
            repo=repo,
            language=language,
            category=category,
            tag=tag,
            limit=limit,
            dense_weight=dense_weight,
            search_mode=mode
        )
        _enrich_code_ast_metadata(results)
        return results
    except ValueError:
        raise
    except Exception as e:
        logger.error(f"Error executing vector search: {e}")
        return []

