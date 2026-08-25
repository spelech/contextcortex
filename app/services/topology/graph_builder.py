import os
import logging
from typing import Optional, Dict, Any, List, Set, Tuple
from collections import deque
from app.services.db import get_db_connection
from app.services.git_manager import format_git_permalink
from app.services.topology.helpers import _clean_filepath, _get_permalink

logger = logging.getLogger("contextcortex.topology")
import sys

def _get_conn():
    top_mod = sys.modules.get("app.services.topology")
    fn = getattr(top_mod, "get_db_connection", get_db_connection) if top_mod else get_db_connection
    return fn()


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

    with _get_conn() as conn:
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

