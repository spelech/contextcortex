import logging
from typing import Optional, List
from app.services.vector_store import get_vector_store, VectorSearchResult

logger = logging.getLogger('contextcortex.search')


from collections import deque
from app.services.database import get_db_connection
from app.services.git_manager import format_git_permalink

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
    Returns formatted ASCII / Markdown call tree detailing symbol hierarchies, file paths, line ranges, and permalinks.
    """
    target_sym = symbol.strip() if symbol else ""
    if not target_sym:
        return "Error: target symbol cannot be empty."

    direction = (direction or "both").lower().strip()
    if direction not in ("callers", "callees", "both"):
        direction = "both"

    depth = max(1, min(5, depth))
    limit = max(1, limit)

    with get_db_connection() as conn:
        # Check if symbol exists in symbols or relationships
        sym_query = "SELECT repo, filepath, name, full_symbol, kind, start_line, end_line FROM ast_symbols WHERE name = ? OR full_symbol = ?"
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
                return f"No symbols or relationships found matching '{target_sym}'."

        # Fetch git repository info for permalink formatting
        git_repos = {}
        for r in conn.execute("SELECT name, url, commit_sha, provider FROM git_repositories").fetchall():
            git_repos[r["name"]] = dict(r)

    def get_permalink(r_repo: str, r_filepath: str, r_line: int) -> Optional[str]:
        g_info = git_repos.get(r_repo)
        if not g_info:
            return None
        rel_path = r_filepath
        if "://" in rel_path:
            rel_path = rel_path.split("://", 1)[1]
        return format_git_permalink(
            g_info["url"],
            g_info["commit_sha"],
            rel_path,
            r_line,
            r_line,
            provider=g_info.get("provider")
        )

    # BFS Queues for callers (inbound) and callees (outbound)
    # Tree nodes structure: {"symbol": str, "children": [...], "rel_type": str, "filepath": str, "line": int, "permalink": str}
    visited_edges = set() # (src_sym, tgt_sym, rel_type, direction) to avoid cycles
    total_returned = 0
    truncated = False

    tree_nodes = []

    with get_db_connection() as conn:
        # Build inbound (callers) sub-tree
        callers_tree = []
        if direction in ("callers", "both"):
            # Queue items: (current_target_symbol, current_level, parent_node_list)
            queue = deque([(target_sym, 1, callers_tree)])
            visited_nodes = {target_sym}

            while queue and total_returned < limit:
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
                if repo:
                    query += " AND r.repo = ?"
                    params.append(repo)
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
                    plink = get_permalink(r["repo"], r["source_filepath"], r["line_number"])

                    node = {
                        "symbol": r["source_symbol"],
                        "rel_type": r["relationship_type"],
                        "filepath": r["source_filepath"],
                        "line": r["line_number"],
                        "start_line": r["start_line"],
                        "end_line": r["end_line"],
                        "repo": r["repo"],
                        "permalink": plink,
                        "children": []
                    }
                    parent_list.append(node)

                    # Continue BFS if within depth limit and symbol not in current path (prevent cycle)
                    if curr_depth < depth and r["source_symbol"] not in visited_nodes:
                        next_visited = set(visited_nodes)
                        next_visited.add(r["source_symbol"])
                        queue.append((r["source_symbol"], curr_depth + 1, node["children"]))

        # Build outbound (callees) sub-tree
        callees_tree = []
        if direction in ("callees", "both") and total_returned < limit:
            queue = deque([(target_sym, 1, callees_tree)])
            visited_nodes = {target_sym}

            while queue and total_returned < limit:
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
                if repo:
                    query += " AND r.repo = ?"
                    params.append(repo)
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
                    plink = get_permalink(r["repo"], r["source_filepath"], r["line_number"])

                    node = {
                        "symbol": r["target_symbol"],
                        "rel_type": r["relationship_type"],
                        "filepath": r["source_filepath"],
                        "line": r["line_number"],
                        "start_line": r["start_line"],
                        "end_line": r["end_line"],
                        "repo": r["repo"],
                        "permalink": plink,
                        "children": []
                    }
                    parent_list.append(node)

                    if curr_depth < depth and r["target_symbol"] not in visited_nodes:
                        next_visited = set(visited_nodes)
                        next_visited.add(r["target_symbol"])
                        queue.append((r["target_symbol"], curr_depth + 1, node["children"]))

    # Render ASCII / Markdown Tree
    lines = [f"# Call Graph Trace: `{target_sym}` (Direction: {direction}, Max Depth: {depth})\n"]
    if symbols_found:
        s0 = symbols_found[0]
        lines.append(f"**Target Symbol Definition:** `{s0['full_symbol'] or s0['name']}` ({s0['kind']}) in `[{s0['repo']}] {s0['filepath']}` (Lines {s0['start_line']}-{s0['end_line']})\n")

    if not callers_tree and not callees_tree:
        lines.append("No relationship edges found within specified depth limit.")
        return "\n".join(lines)

    def render_tree_node(node, prefix="", is_last=True):
        connector = "└── " if is_last else "├── "
        rel_info = f"[{node['rel_type']}]"
        fp_info = f"`{node['filepath']}`:{node['line']}"
        link_str = f" ([permalink]({node['permalink']}))" if node.get("permalink") else ""

        node_str = f"{prefix}{connector}{rel_info} **{node['symbol']}** in {fp_info}{link_str}"
        child_prefix = prefix + ("    " if is_last else "│   ")

        child_lines = [node_str]
        for idx, child in enumerate(node["children"]):
            last_child = (idx == len(node["children"]) - 1)
            child_lines.extend(render_tree_node(child, prefix=child_prefix, is_last=last_child))
        return child_lines

    if direction in ("callers", "both") and callers_tree:
        lines.append("### Callers (Inbound Dependencies / Invoked By)")
        for idx, node in enumerate(callers_tree):
            lines.extend(render_tree_node(node, is_last=(idx == len(callers_tree) - 1)))
        lines.append("")

    if direction in ("callees", "both") and callees_tree:
        lines.append("### Callees (Outbound Dependencies / Invokes)")
        for idx, node in enumerate(callees_tree):
            lines.extend(render_tree_node(node, is_last=(idx == len(callees_tree) - 1)))
        lines.append("")

    if truncated or total_returned >= limit:
        lines.append(f"\n*Note: Relationship output truncated at maximum limit of {limit} entries.*")

    return "\n".join(lines)


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
        results = store.search(
            query_text=query_text.strip(),
            doc_type=doc_type,
            repo=repo,
            language=language,
            category=category,
            tag=tag,
            limit=limit,
            dense_weight=dense_weight,
            search_mode=search_mode
        )
        _enrich_code_ast_metadata(results)
        return results
    except Exception as e:
        logger.error(f"Error executing vector search: {e}")
        return []

