import os
import re
from typing import Optional, Dict, Any, List, Set, Tuple
from collections import deque
from app.services.db import get_db_connection
from app.services.git_manager import format_git_permalink

def _clean_filepath(fp: str) -> str:
    if "://" in fp:
        return fp.split("://", 1)[1]
    return fp

def _get_permalink(
    git_repos: Dict[str, Dict[str, Any]],
    repo: str,
    filepath: str,
    start_line: Optional[int] = None,
    end_line: Optional[int] = None
) -> Optional[str]:
    g_info = git_repos.get(repo)
    if not g_info or not g_info.get("url"):
        return None
    clean_fp = _clean_filepath(filepath)
    return format_git_permalink(
        g_info["url"],
        g_info.get("commit_sha"),
        clean_fp,
        start_line,
        end_line,
        provider=g_info.get("provider")
    )

def _read_code_snippet(
    filepath: str,
    start_line: Optional[int] = None,
    end_line: Optional[int] = None,
    max_lines: int = 100
) -> Optional[str]:
    """Attempts to read source code snippet from local filesystem if accessible."""
    clean_fp = _clean_filepath(filepath)
    candidate_paths = [
        clean_fp,
        os.path.abspath(clean_fp),
        os.path.join(os.getcwd(), clean_fp),
        os.path.join(os.getcwd(), "contexthub", clean_fp),
    ]
    
    found_path = None
    for cp in candidate_paths:
        if os.path.isfile(cp):
            found_path = cp
            break
            
    if not found_path:
        return None

    try:
        with open(found_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            
        s_line = max(1, start_line or 1)
        e_line = min(len(lines), end_line or len(lines))
        
        if e_line - s_line > max_lines:
            e_line = s_line + max_lines
            
        snippet = "".join(lines[s_line - 1:e_line])
        return snippet.rstrip()
    except Exception:
        return None

def get_topology_graph(
    repo: str,
    view_type: str = "files",
    depth: int = 2,
    root_node: Optional[str] = None,
    limit: int = 300
) -> Optional[Dict[str, Any]]:
    """
    Constructs a visual codebase dependency and route topology graph.
    Supports filtering by view_type ('files', 'symbols', 'routes', 'full'),
    root_node BFS traversal up to depth, and pagination limits.
    """
    v_type = (view_type or "files").lower().strip()
    if v_type not in ("files", "symbols", "routes", "full"):
        v_type = "files"

    depth = max(1, min(10, depth))
    limit = max(1, min(2000, limit))

    with get_db_connection() as conn:
        # 1. Verify repository existence if not __all__
        if repo != "__all__":
            repo_exists = conn.execute(
                "SELECT 1 FROM git_repositories WHERE name = ? UNION SELECT 1 FROM indexed_paths WHERE repo = ? UNION SELECT 1 FROM indexed_files WHERE repo = ?",
                (repo, repo, repo)
            ).fetchone()
            if not repo_exists:
                return None

        # Fetch git repository info for permalinks
        git_repos: Dict[str, Dict[str, Any]] = {}
        for r in conn.execute("SELECT name, url, commit_sha, provider FROM git_repositories").fetchall():
            git_repos[r["name"]] = dict(r)

        # 2. Fetch raw tables based on repo filter
        where_repo = "" if repo == "__all__" else " WHERE repo = ?"
        params = [] if repo == "__all__" else [repo]

        file_rows = conn.execute(f"SELECT filepath, repo, doc_type, language, commit_sha FROM indexed_files{where_repo}", params).fetchall()
        symbol_rows = conn.execute(f"SELECT id, repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language FROM ast_symbols{where_repo}", params).fetchall()
        rel_rows = conn.execute(f"SELECT id, repo, source_symbol_id, source_filepath, source_symbol, target_symbol, relationship_type, line_number FROM ast_relationships{where_repo}", params).fetchall()
        route_rows = conn.execute(f"SELECT id, repo, filepath, framework, http_method, path_pattern, handler_symbol, start_line, end_line FROM api_routes{where_repo}", params).fetchall()
        call_rows = conn.execute(f"SELECT id, repo, filepath, http_method, url_pattern, caller_symbol, line_number FROM api_client_calls{where_repo}", params).fetchall()

    # 3. Build Node Catalog
    all_nodes: Dict[str, Dict[str, Any]] = {}
    
    # File nodes & Module directory nodes
    file_id_by_path: Dict[Tuple[str, str], str] = {}
    for r in file_rows:
        clean_fp = _clean_filepath(r["filepath"])
        f_id = f"file:{r['repo']}:{clean_fp}"
        file_id_by_path[(r["repo"], clean_fp)] = f_id
        file_id_by_path[(r["repo"], r["filepath"])] = f_id
        
        all_nodes[f_id] = {
            "id": f_id,
            "name": os.path.basename(clean_fp) or clean_fp,
            "type": "file",
            "repo": r["repo"],
            "filepath": clean_fp,
            "language": r["language"] or "text",
            "metadata": {
                "doc_type": r["doc_type"],
                "commit_sha": r["commit_sha"],
                "language": r["language"]
            }
        }

    # Symbol nodes
    symbol_id_by_db_id: Dict[int, str] = {}
    symbols_by_name: Dict[Tuple[str, str], List[str]] = {}
    symbols_by_file: Dict[Tuple[str, str], List[str]] = {}
    
    for r in symbol_rows:
        clean_fp = _clean_filepath(r["filepath"])
        s_id = f"symbol:{r['id']}"
        symbol_id_by_db_id[r["id"]] = s_id
        
        key_name = (r["repo"], r["name"])
        symbols_by_name.setdefault(key_name, []).append(s_id)
        
        key_file = (r["repo"], clean_fp)
        symbols_by_file.setdefault(key_file, []).append(s_id)

        kind_lower = (r["kind"] or "").lower()
        if kind_lower in ("class", "interface", "struct", "enum", "trait", "type"):
            node_type = "class"
        else:
            node_type = "function"

        all_nodes[s_id] = {
            "id": s_id,
            "name": r["name"],
            "type": node_type,
            "repo": r["repo"],
            "filepath": clean_fp,
            "kind": r["kind"],
            "start_line": r["start_line"],
            "end_line": r["end_line"],
            "signature": r["signature"],
            "language": r["language"],
            "metadata": {
                "full_symbol": r["full_symbol"],
                "kind": r["kind"]
            }
        }

    # Route nodes
    route_id_by_db_id: Dict[int, str] = {}
    routes_by_pattern: Dict[Tuple[str, str], List[str]] = {}
    
    for r in route_rows:
        clean_fp = _clean_filepath(r["filepath"])
        rt_id = f"route:{r['id']}"
        route_id_by_db_id[r["id"]] = rt_id
        
        pattern_key = (r["repo"], r["path_pattern"])
        routes_by_pattern.setdefault(pattern_key, []).append(rt_id)

        all_nodes[rt_id] = {
            "id": rt_id,
            "name": f"{r['http_method'].upper()} {r['path_pattern']}",
            "type": "route",
            "repo": r["repo"],
            "filepath": clean_fp,
            "method": r["http_method"].upper(),
            "path_pattern": r["path_pattern"],
            "start_line": r["start_line"],
            "end_line": r["end_line"],
            "metadata": {
                "framework": r["framework"],
                "handler_symbol": r["handler_symbol"]
            }
        }

    # 4. Build Edge Catalog
    all_edges: List[Dict[str, Any]] = []
    seen_edges: Set[Tuple[str, str, str]] = set()

    def add_edge(src: str, tgt: str, e_type: str, line: Optional[int] = None, label: Optional[str] = None):
        if not src or not tgt or src == tgt:
            return
        if (src, tgt, e_type) in seen_edges:
            return
        seen_edges.add((src, tgt, e_type))
        all_edges.append({
            "source": src,
            "target": tgt,
            "type": e_type,
            "line_number": line,
            "label": label or e_type
        })

    # DEFINES Edges:
    # File -> Symbols
    for r in symbol_rows:
        clean_fp = _clean_filepath(r["filepath"])
        f_id = file_id_by_path.get((r["repo"], clean_fp))
        s_id = symbol_id_by_db_id.get(r["id"])
        if f_id and s_id:
            add_edge(f_id, s_id, "DEFINES", r["start_line"])

    # File -> Routes
    for r in route_rows:
        clean_fp = _clean_filepath(r["filepath"])
        f_id = file_id_by_path.get((r["repo"], clean_fp))
        rt_id = route_id_by_db_id.get(r["id"])
        if f_id and rt_id:
            add_edge(f_id, rt_id, "DEFINES", r["start_line"])

    # HANDLES Edges: Route -> Handler Symbol
    for r in route_rows:
        rt_id = route_id_by_db_id.get(r["id"])
        h_sym = r["handler_symbol"]
        if rt_id and h_sym:
            # Match symbol in same repo / file
            matched_sym_ids = symbols_by_name.get((r["repo"], h_sym), [])
            if not matched_sym_ids:
                # Fallback cross-repo search for handler name
                for (sym_repo, sym_name), s_ids in symbols_by_name.items():
                    if sym_name == h_sym:
                        matched_sym_ids = s_ids
                        break
            for s_id in matched_sym_ids:
                add_edge(rt_id, s_id, "HANDLES", r["start_line"])

    # ROUTES_TO Edges: Client Call -> Route
    for c in call_rows:
        c_pattern = c["url_pattern"]
        matched_route_ids = routes_by_pattern.get((c["repo"], c_pattern), [])
        if not matched_route_ids:
            for (rt_repo, rt_pat), rt_ids in routes_by_pattern.items():
                if rt_pat == c_pattern or c_pattern.rstrip("/") == rt_pat.rstrip("/"):
                    matched_route_ids = rt_ids
                    break
        
        # Source of client call (caller symbol or file)
        clean_c_fp = _clean_filepath(c["filepath"])
        caller_node_id = None
        if c["caller_symbol"]:
            caller_syms = symbols_by_name.get((c["repo"], c["caller_symbol"]), [])
            if caller_syms:
                caller_node_id = caller_syms[0]
        if not caller_node_id:
            caller_node_id = file_id_by_path.get((c["repo"], clean_c_fp))

        if caller_node_id:
            for rt_id in matched_route_ids:
                add_edge(caller_node_id, rt_id, "ROUTES_TO", c["line_number"])

    # AST Relationships (IMPORTS, CALLS, DEFINES)
    for rel in rel_rows:
        rel_type = (rel["relationship_type"] or "CALLS").upper()
        if rel_type not in ("IMPORTS", "CALLS", "DEFINES", "HANDLES", "ROUTES_TO"):
            rel_type = "CALLS"

        src_s_id = symbol_id_by_db_id.get(rel["source_symbol_id"])
        if not src_s_id and rel["source_symbol"]:
            src_candidates = symbols_by_name.get((rel["repo"], rel["source_symbol"]), [])
            if src_candidates:
                src_s_id = src_candidates[0]

        clean_src_fp = _clean_filepath(rel["source_filepath"])
        src_f_id = file_id_by_path.get((rel["repo"], clean_src_fp))

        tgt_sym_name = rel["target_symbol"]
        tgt_s_ids = symbols_by_name.get((rel["repo"], tgt_sym_name), [])
        if not tgt_s_ids:
            # Try finding across all repos
            for (s_repo, s_name), s_ids in symbols_by_name.items():
                if s_name == tgt_sym_name or s_name.endswith(f".{tgt_sym_name}"):
                    tgt_s_ids = s_ids
                    break

        # Edge between symbols
        if src_s_id and tgt_s_ids:
            for tgt_id in tgt_s_ids:
                add_edge(src_s_id, tgt_id, rel_type, rel["line_number"])

        # Edge between files (derived from symbol relationships or file imports)
        if src_f_id and tgt_s_ids:
            for tgt_id in tgt_s_ids:
                tgt_node = all_nodes.get(tgt_id)
                if tgt_node and tgt_node.get("filepath"):
                    tgt_f_id = file_id_by_path.get((tgt_node["repo"], tgt_node["filepath"]))
                    if tgt_f_id and tgt_f_id != src_f_id:
                        add_edge(src_f_id, tgt_f_id, "IMPORTS" if rel_type == "IMPORTS" else "CALLS", rel["line_number"])

    # 5. Filter Nodes and Edges by View Type
    filtered_nodes: Dict[str, Dict[str, Any]] = {}
    filtered_edges: List[Dict[str, Any]] = []

    if v_type == "files":
        for nid, node in all_nodes.items():
            if node["type"] == "file":
                filtered_nodes[nid] = node
        for edge in all_edges:
            if edge["source"] in filtered_nodes and edge["target"] in filtered_nodes:
                filtered_edges.append(edge)

    elif v_type == "symbols":
        for nid, node in all_nodes.items():
            if node["type"] in ("class", "function"):
                filtered_nodes[nid] = node
        for edge in all_edges:
            if edge["source"] in filtered_nodes and edge["target"] in filtered_nodes:
                filtered_edges.append(edge)

    elif v_type == "routes":
        # Include routes, handlers, and client callers
        route_nodes = {nid: node for nid, node in all_nodes.items() if node["type"] == "route"}
        filtered_nodes.update(route_nodes)
        
        # Include nodes connected to routes via HANDLES, ROUTES_TO, DEFINES
        for edge in all_edges:
            if edge["type"] in ("HANDLES", "ROUTES_TO", "DEFINES"):
                if edge["source"] in route_nodes and edge["target"] in all_nodes:
                    filtered_nodes[edge["target"]] = all_nodes[edge["target"]]
                elif edge["target"] in route_nodes and edge["source"] in all_nodes:
                    filtered_nodes[edge["source"]] = all_nodes[edge["source"]]

        for edge in all_edges:
            if edge["source"] in filtered_nodes and edge["target"] in filtered_nodes:
                filtered_edges.append(edge)

    else:  # "full"
        filtered_nodes = dict(all_nodes)
        filtered_edges = list(all_edges)

    # 6. Apply Root Node BFS Filtering if requested
    if root_node and root_node.strip():
        r_target = root_node.strip().lower()
        matched_start_id = None

        # Try exact ID match
        for nid in filtered_nodes:
            if nid.lower() == r_target:
                matched_start_id = nid
                break
        
        # Try name match
        if not matched_start_id:
            for nid, n in filtered_nodes.items():
                if n["name"].lower() == r_target:
                    matched_start_id = nid
                    break

        # Try filepath or path_pattern match
        if not matched_start_id:
            for nid, n in filtered_nodes.items():
                if n.get("filepath", "").lower() == r_target or n.get("path_pattern", "").lower() == r_target:
                    matched_start_id = nid
                    break

        # If still not found, search in all_nodes to see if it exists in another view
        if not matched_start_id:
            for nid, n in all_nodes.items():
                if nid.lower() == r_target or n["name"].lower() == r_target or n.get("filepath", "").lower() == r_target:
                    matched_start_id = nid
                    filtered_nodes[nid] = n
                    break

        if not matched_start_id:
            return {
                "nodes": [],
                "edges": [],
                "stats": {"node_count": 0, "edge_count": 0}
            }

        # Build adjacency for BFS
        adj: Dict[str, Set[str]] = {}
        for edge in all_edges:
            adj.setdefault(edge["source"], set()).add(edge["target"])
            adj.setdefault(edge["target"], set()).add(edge["source"])

        visited: Set[str] = {matched_start_id}
        queue = deque([(matched_start_id, 0)])

        while queue and len(visited) < limit:
            curr_id, curr_d = queue.popleft()
            if curr_d >= depth:
                continue
            for neighbor in adj.get(curr_id, set()):
                if neighbor not in visited and len(visited) < limit:
                    visited.add(neighbor)
                    if neighbor in all_nodes:
                        filtered_nodes[neighbor] = all_nodes[neighbor]
                    queue.append((neighbor, curr_d + 1))

        # Filter nodes to visited set
        final_nodes = [filtered_nodes[nid] for nid in visited if nid in filtered_nodes]
        final_node_ids = {n["id"] for n in final_nodes}
        final_edges = [
            e for e in all_edges 
            if e["source"] in final_node_ids and e["target"] in final_node_ids
        ]
        return {
            "nodes": final_nodes,
            "edges": final_edges,
            "stats": {"node_count": len(final_nodes), "edge_count": len(final_edges)}
        }

    # 7. Apply Limit Pagination
    nodes_list = list(filtered_nodes.values())
    if len(nodes_list) > limit:
        # Calculate degree for each node to retain most connected/informative nodes
        node_degrees: Dict[str, int] = {}
        for edge in filtered_edges:
            node_degrees[edge["source"]] = node_degrees.get(edge["source"], 0) + 1
            node_degrees[edge["target"]] = node_degrees.get(edge["target"], 0) + 1

        nodes_list.sort(key=lambda n: node_degrees.get(n["id"], 0), reverse=True)
        nodes_list = nodes_list[:limit]

    retained_ids = {n["id"] for n in nodes_list}
    final_edges = [e for e in filtered_edges if e["source"] in retained_ids and e["target"] in retained_ids]

    return {
        "nodes": nodes_list,
        "edges": final_edges,
        "stats": {
            "node_count": len(nodes_list),
            "edge_count": len(final_edges)
        }
    }

def get_node_details(node_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieves rich inspection details for a node:
    source snippet/signature, line ranges, permalinks, incoming and outgoing neighbors.
    """
    if not node_id:
        return None

    with get_db_connection() as conn:
        git_repos: Dict[str, Dict[str, Any]] = {}
        for r in conn.execute("SELECT name, url, commit_sha, provider FROM git_repositories").fetchall():
            git_repos[r["name"]] = dict(r)

        # 1. Handle Symbol Node
        if node_id.startswith("symbol:") or (node_id.isdigit() and int(node_id) > 0):
            sym_id_raw = node_id.split("symbol:", 1)[1] if "symbol:" in node_id else node_id
            sym_row = None
            if sym_id_raw.isdigit():
                sym_row = conn.execute(
                    "SELECT id, repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language FROM ast_symbols WHERE id = ?",
                    (int(sym_id_raw),)
                ).fetchone()

            if not sym_row:
                sym_row = conn.execute(
                    "SELECT id, repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language FROM ast_symbols WHERE name = ? OR full_symbol = ? LIMIT 1",
                    (node_id, node_id)
                ).fetchone()

            if not sym_row:
                return None

            clean_fp = _clean_filepath(sym_row["filepath"])
            s_type = "class" if (sym_row["kind"] or "").lower() in ("class", "interface", "struct", "enum") else "function"
            plink = _get_permalink(git_repos, sym_row["repo"], clean_fp, sym_row["start_line"], sym_row["end_line"])
            code_prev = _read_code_snippet(clean_fp, sym_row["start_line"], sym_row["end_line"]) or sym_row["signature"]

            # Incoming (Callers & Importers)
            incoming = []
            in_rows = conn.execute(
                "SELECT r.id, r.repo, r.source_filepath, r.source_symbol, r.relationship_type, r.line_number, s.id as sym_id, s.kind "
                "FROM ast_relationships r "
                "LEFT JOIN ast_symbols s ON r.source_symbol_id = s.id "
                "WHERE r.target_symbol = ? OR r.target_symbol = ? ORDER BY r.line_number ASC",
                (sym_row["name"], sym_row["full_symbol"] or sym_row["name"])
            ).fetchall()

            for ir in in_rows:
                neighbor_id = f"symbol:{ir['sym_id']}" if ir["sym_id"] else f"file:{ir['repo']}:{_clean_filepath(ir['source_filepath'])}"
                incoming.append({
                    "id": neighbor_id,
                    "name": ir["source_symbol"] or os.path.basename(ir["source_filepath"]),
                    "type": "function" if ir["source_symbol"] else "file",
                    "edge_type": (ir["relationship_type"] or "CALLS").upper(),
                    "filepath": _clean_filepath(ir["source_filepath"]),
                    "line_number": ir["line_number"],
                    "permalink": _get_permalink(git_repos, ir["repo"], ir["source_filepath"], ir["line_number"], ir["line_number"])
                })

            # Outgoing (Callees & Imports)
            outgoing = []
            out_rows = conn.execute(
                "SELECT r.id, r.repo, r.target_symbol, r.relationship_type, r.line_number, s.id as sym_id, s.filepath as tgt_fp "
                "FROM ast_relationships r "
                "LEFT JOIN ast_symbols s ON (r.target_symbol = s.name AND r.repo = s.repo) "
                "WHERE r.source_symbol_id = ? OR r.source_symbol = ? ORDER BY r.line_number ASC",
                (sym_row["id"], sym_row["name"])
            ).fetchall()

            for orw in out_rows:
                neighbor_id = f"symbol:{orw['sym_id']}" if orw["sym_id"] else f"symbol:{orw['target_symbol']}"
                outgoing.append({
                    "id": neighbor_id,
                    "name": orw["target_symbol"],
                    "type": "function",
                    "edge_type": (orw["relationship_type"] or "CALLS").upper(),
                    "filepath": _clean_filepath(orw["tgt_fp"]) if orw["tgt_fp"] else None,
                    "line_number": orw["line_number"],
                    "permalink": _get_permalink(git_repos, orw["repo"], orw["tgt_fp"], orw["line_number"]) if orw["tgt_fp"] else None
                })

            return {
                "id": f"symbol:{sym_row['id']}",
                "name": sym_row["name"],
                "type": s_type,
                "repo": sym_row["repo"],
                "filepath": clean_fp,
                "start_line": sym_row["start_line"],
                "end_line": sym_row["end_line"],
                "signature": sym_row["signature"],
                "code_preview": code_prev,
                "permalink": plink,
                "incoming": incoming,
                "outgoing": outgoing,
                "metadata": {
                    "kind": sym_row["kind"],
                    "full_symbol": sym_row["full_symbol"],
                    "language": sym_row["language"]
                }
            }

        # 2. Handle File Node
        if node_id.startswith("file:") or "." in node_id:
            raw_fp = node_id.split("file:", 1)[1] if "file:" in node_id else node_id
            repo_candidate = None
            if ":" in raw_fp:
                parts = raw_fp.split(":", 1)
                repo_candidate = parts[0]
                raw_fp = parts[1]

            f_query = "SELECT filepath, repo, doc_type, language, commit_sha FROM indexed_files WHERE filepath = ? OR filepath LIKE ?"
            f_params = [raw_fp, f"%{raw_fp}"]
            if repo_candidate:
                f_query += " AND repo = ?"
                f_params.append(repo_candidate)

            file_row = conn.execute(f_query, f_params).fetchone()
            if not file_row:
                # Try finding in file_summaries
                file_row = conn.execute("SELECT filepath, repo, category as doc_type, 'text' as language, '' as commit_sha FROM file_summaries WHERE filepath = ? OR filepath LIKE ? LIMIT 1", [raw_fp, f"%{raw_fp}"]).fetchone()

            if not file_row:
                return None

            clean_fp = _clean_filepath(file_row["filepath"])
            plink = _get_permalink(git_repos, file_row["repo"], clean_fp, 1, 50)
            code_prev = _read_code_snippet(clean_fp, 1, 50)

            # Incoming (Files or symbols that import or call this file's symbols)
            incoming = []
            in_file_rows = conn.execute(
                "SELECT DISTINCT r.repo, r.source_filepath, r.source_symbol, r.relationship_type, r.line_number "
                "FROM ast_relationships r "
                "WHERE r.target_symbol IN (SELECT name FROM ast_symbols WHERE filepath = ? OR filepath LIKE ?) "
                "AND r.source_filepath != ? ORDER BY r.line_number ASC",
                (file_row["filepath"], f"%{clean_fp}", file_row["filepath"])
            ).fetchall()

            for ifr in in_file_rows:
                incoming.append({
                    "id": f"file:{ifr['repo']}:{_clean_filepath(ifr['source_filepath'])}",
                    "name": os.path.basename(ifr["source_filepath"]),
                    "type": "file",
                    "edge_type": (ifr["relationship_type"] or "IMPORTS").upper(),
                    "filepath": _clean_filepath(ifr["source_filepath"]),
                    "line_number": ifr["line_number"],
                    "permalink": _get_permalink(git_repos, ifr["repo"], ifr["source_filepath"], ifr["line_number"])
                })

            # Outgoing (Files or symbols imported/called by this file)
            outgoing = []
            out_file_rows = conn.execute(
                "SELECT DISTINCT r.repo, r.target_symbol, r.relationship_type, r.line_number, s.filepath as tgt_fp "
                "FROM ast_relationships r "
                "LEFT JOIN ast_symbols s ON (r.target_symbol = s.name AND r.repo = s.repo) "
                "WHERE (r.source_filepath = ? OR r.source_filepath LIKE ?) "
                "ORDER BY r.line_number ASC",
                (file_row["filepath"], f"%{clean_fp}")
            ).fetchall()

            for ofr in out_file_rows:
                tgt_fp = ofr["tgt_fp"]
                outgoing.append({
                    "id": f"file:{ofr['repo']}:{_clean_filepath(tgt_fp)}" if tgt_fp else f"symbol:{ofr['target_symbol']}",
                    "name": os.path.basename(tgt_fp) if tgt_fp else ofr["target_symbol"],
                    "type": "file" if tgt_fp else "function",
                    "edge_type": (ofr["relationship_type"] or "IMPORTS").upper(),
                    "filepath": _clean_filepath(tgt_fp) if tgt_fp else None,
                    "line_number": ofr["line_number"],
                    "permalink": _get_permalink(git_repos, ofr["repo"], tgt_fp, ofr["line_number"]) if tgt_fp else None
                })

            return {
                "id": f"file:{file_row['repo']}:{clean_fp}",
                "name": os.path.basename(clean_fp),
                "type": "file",
                "repo": file_row["repo"],
                "filepath": clean_fp,
                "start_line": 1,
                "end_line": 50,
                "signature": f"File: {clean_fp}",
                "code_preview": code_prev,
                "permalink": plink,
                "incoming": incoming,
                "outgoing": outgoing,
                "metadata": {
                    "doc_type": file_row["doc_type"],
                    "language": file_row["language"],
                    "commit_sha": file_row["commit_sha"]
                }
            }

        # 3. Handle Route Node
        if node_id.startswith("route:") or "/" in node_id:
            raw_rt = node_id.split("route:", 1)[1] if "route:" in node_id else node_id
            rt_row = None
            if raw_rt.isdigit():
                rt_row = conn.execute(
                    "SELECT id, repo, filepath, framework, http_method, path_pattern, handler_symbol, start_line, end_line FROM api_routes WHERE id = ?",
                    (int(raw_rt),)
                ).fetchone()

            if not rt_row:
                rt_row = conn.execute(
                    "SELECT id, repo, filepath, framework, http_method, path_pattern, handler_symbol, start_line, end_line FROM api_routes WHERE path_pattern = ? OR path_pattern LIKE ? LIMIT 1",
                    (node_id, f"%{node_id}")
                ).fetchone()

            if not rt_row:
                return None

            clean_fp = _clean_filepath(rt_row["filepath"])
            plink = _get_permalink(git_repos, rt_row["repo"], clean_fp, rt_row["start_line"], rt_row["end_line"])
            code_prev = _read_code_snippet(clean_fp, rt_row["start_line"], rt_row["end_line"])

            # Incoming (API Client Calls)
            incoming = []
            calls = conn.execute(
                "SELECT filepath, http_method, url_pattern, caller_symbol, line_number, repo FROM api_client_calls WHERE url_pattern = ? OR url_pattern LIKE ?",
                (rt_row["path_pattern"], f"%{rt_row['path_pattern']}")
            ).fetchall()

            for c in calls:
                incoming.append({
                    "id": f"file:{c['repo']}:{_clean_filepath(c['filepath'])}",
                    "name": c["caller_symbol"] or os.path.basename(c["filepath"]),
                    "type": "function" if c["caller_symbol"] else "file",
                    "edge_type": "ROUTES_TO",
                    "filepath": _clean_filepath(c["filepath"]),
                    "line_number": c["line_number"],
                    "permalink": _get_permalink(git_repos, c["repo"], c["filepath"], c["line_number"])
                })

            # Outgoing (Handler symbol and downstream calls)
            outgoing = []
            if rt_row["handler_symbol"]:
                sym_match = conn.execute(
                    "SELECT id, filepath, start_line, end_line FROM ast_symbols WHERE name = ? AND repo = ? LIMIT 1",
                    (rt_row["handler_symbol"], rt_row["repo"])
                ).fetchone()

                outgoing.append({
                    "id": f"symbol:{sym_match['id']}" if sym_match else f"symbol:{rt_row['handler_symbol']}",
                    "name": rt_row["handler_symbol"],
                    "type": "function",
                    "edge_type": "HANDLES",
                    "filepath": _clean_filepath(sym_match["filepath"]) if sym_match else clean_fp,
                    "line_number": sym_match["start_line"] if sym_match else rt_row["start_line"],
                    "permalink": _get_permalink(git_repos, rt_row["repo"], sym_match["filepath"] if sym_match else clean_fp, sym_match["start_line"] if sym_match else rt_row["start_line"])
                })

            return {
                "id": f"route:{rt_row['id']}",
                "name": f"{rt_row['http_method'].upper()} {rt_row['path_pattern']}",
                "type": "route",
                "repo": rt_row["repo"],
                "filepath": clean_fp,
                "start_line": rt_row["start_line"],
                "end_line": rt_row["end_line"],
                "signature": f"Route: {rt_row['http_method'].upper()} {rt_row['path_pattern']}",
                "code_preview": code_prev,
                "permalink": plink,
                "incoming": incoming,
                "outgoing": outgoing,
                "metadata": {
                    "framework": rt_row["framework"],
                    "http_method": rt_row["http_method"],
                    "path_pattern": rt_row["path_pattern"],
                    "handler_symbol": rt_row["handler_symbol"]
                }
            }

        # 4. Fallback search by ID or name across symbols, files, routes
        sym_fallback = conn.execute(
            "SELECT id FROM ast_symbols WHERE name = ? LIMIT 1", (node_id,)
        ).fetchone()
        if sym_fallback:
            return get_node_details(f"symbol:{sym_fallback['id']}")

        file_fallback = conn.execute(
            "SELECT filepath, repo FROM indexed_files WHERE filepath LIKE ? LIMIT 1", (f"%{node_id}",)
        ).fetchone()
        if file_fallback:
            return get_node_details(f"file:{file_fallback['repo']}:{file_fallback['filepath']}")

    return None
