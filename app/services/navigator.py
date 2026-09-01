import os
import logging
from typing import Optional, Dict, Any, List
from app.services.database import get_db_connection

logger = logging.getLogger("contextcortex.navigator")

def _clean_path(p: str) -> str:
    return p.replace("\\", "/").strip("/")

def get_navigator_tree(repo: str) -> Optional[Dict[str, Any]]:
    with get_db_connection() as conn:
        where = "" if repo == "__all__" else " WHERE repo = ?"
        params = [] if repo == "__all__" else [repo]
        
        file_rows = conn.execute(
            f"SELECT filepath, repo, doc_type, language FROM indexed_files{where} ORDER BY filepath",
            params
        ).fetchall()
        
        if not file_rows and repo != "__all__":
            # Verify if repo exists
            repo_exists = conn.execute(
                "SELECT 1 FROM git_repositories WHERE name = ? UNION SELECT 1 FROM indexed_paths WHERE repo = ?",
                (repo, repo)
            ).fetchone()
            if not repo_exists:
                return None

        # Fetch symbol counts per file
        sym_counts = {}
        for row in conn.execute(
            f"SELECT filepath, count(*) as cnt FROM ast_symbols{where} GROUP BY filepath",
            params
        ).fetchall():
            sym_counts[_clean_path(row["filepath"])] = row["cnt"]

        # Fetch route counts per file
        route_counts = {}
        for row in conn.execute(
            f"SELECT filepath, count(*) as cnt FROM api_routes{where} GROUP BY filepath",
            params
        ).fetchall():
            route_counts[_clean_path(row["filepath"])] = row["cnt"]

    # Build hierarchical tree
    root = {"children": {}}
    for f in file_rows:
        raw_path = _clean_path(f["filepath"])
        parts = raw_path.split("/")
        curr = root
        for i, part in enumerate(parts):
            is_last = (i == len(parts) - 1)
            if part not in curr["children"]:
                curr["children"][part] = {
                    "id": f"{'file' if is_last else 'dir'}:{'/'.join(parts[:i+1])}",
                    "name": part,
                    "is_dir": not is_last,
                    "path": "/".join(parts[:i+1]),
                    "children": {} if not is_last else None,
                    "language": f["language"] if is_last else None,
                    "symbol_count": sym_counts.get(raw_path, 0) if is_last else 0,
                    "route_count": route_counts.get(raw_path, 0) if is_last else 0,
                }
            curr = curr["children"][part]

    def _format_node(n):
        node = {
            "id": n["id"],
            "name": n["name"],
            "is_dir": n["is_dir"],
            "path": n["path"],
            "language": n["language"],
            "symbol_count": n["symbol_count"],
            "route_count": n["route_count"],
        }
        if n["is_dir"]:
            node["children"] = [_format_node(c) for c in n["children"].values()]
            # Aggregate child counts
            node["symbol_count"] = sum(c["symbol_count"] for c in node["children"])
            node["route_count"] = sum(c["route_count"] for c in node["children"])
        return node

    tree = [_format_node(c) for c in root["children"].values()]
    return {
        "repo": repo,
        "total_files": len(file_rows),
        "total_symbols": sum(sym_counts.values()),
        "tree": tree
    }

def get_file_outline(repo: str, filepath: str) -> Optional[Dict[str, Any]]:
    clean_fp = _clean_path(filepath)
    with get_db_connection() as conn:
        where = " WHERE filepath LIKE ? " if repo == "__all__" else " WHERE repo = ? AND filepath LIKE ? "
        params = [f"%{clean_fp}"] if repo == "__all__" else [repo, f"%{clean_fp}"]
        
        symbols = conn.execute(
            f"SELECT id, repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language FROM ast_symbols{where} ORDER BY start_line ASC",
            params
        ).fetchall()

        routes = conn.execute(
            f"SELECT id, framework, http_method, path_pattern, handler_symbol, start_line, end_line FROM api_routes{where}",
            params
        ).fetchall()

    route_by_handler = {r["handler_symbol"]: dict(r) for r in routes if r["handler_symbol"]}
    route_by_line = {r["start_line"]: dict(r) for r in routes}

    formatted_symbols = []
    for s in symbols:
        route_meta = route_by_handler.get(s["name"]) or route_by_line.get(s["start_line"])
        formatted_symbols.append({
            "id": s["id"],
            "name": s["name"],
            "full_symbol": s["full_symbol"],
            "kind": s["kind"],
            "start_line": s["start_line"],
            "end_line": s["end_line"],
            "signature": s["signature"],
            "language": s["language"],
            "route": route_meta
        })

    return {
        "repo": repo,
        "filepath": clean_fp,
        "symbols": formatted_symbols
    }

def get_symbol_impact(repo: str, symbol_id: int) -> Optional[Dict[str, Any]]:
    with get_db_connection() as conn:
        sym = conn.execute(
            "SELECT id, repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language FROM ast_symbols WHERE id = ?",
            (symbol_id,)
        ).fetchone()
        
        if not sym:
            return None

        # Fetch incoming callers
        callers = conn.execute(
            "SELECT id, source_symbol_id, source_filepath, source_symbol, target_symbol, relationship_type, line_number FROM ast_relationships WHERE target_symbol = ? OR source_symbol_id = ?",
            (sym["name"], sym["id"])
        ).fetchall()

        # Fetch outgoing dependencies
        callees = conn.execute(
            "SELECT id, target_symbol, relationship_type, line_number FROM ast_relationships WHERE source_symbol_id = ? AND relationship_type != 'IMPORTS'",
            (sym["id"],)
        ).fetchall()

        imports = conn.execute(
            "SELECT id, target_symbol, line_number FROM ast_relationships WHERE source_symbol_id = ? AND relationship_type = 'IMPORTS'",
            (sym["id"],)
        ).fetchall()

        route = conn.execute(
            "SELECT framework, http_method, path_pattern FROM api_routes WHERE handler_symbol = ? OR (filepath LIKE ? AND start_line <= ? AND end_line >= ?)",
            (sym["name"], f"%{_clean_path(sym['filepath'])}", sym["start_line"], sym["end_line"])
        ).fetchone()

    return {
        "symbol": dict(sym),
        "route": dict(route) if route else None,
        "callers": [dict(c) for c in callers],
        "callees": [dict(c) for c in callees],
        "imports": [dict(i) for i in imports]
    }
