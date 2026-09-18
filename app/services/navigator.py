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
        repo_filter = "" if repo == "__all__" else "repo = ? AND "
        repo_params = [] if repo == "__all__" else [repo]

        # First attempt exact filepath match (relative or with leading slash)
        symbols = conn.execute(
            f"SELECT id, repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language "
            f"FROM ast_symbols WHERE {repo_filter}(filepath = ? OR filepath = ?) ORDER BY start_line ASC",
            repo_params + [clean_fp, f"/{clean_fp}"]
        ).fetchall()

        # If no exact match, fallback to slash-anchored suffix match to prevent cross-file symbol leakage
        if not symbols:
            symbols = conn.execute(
                f"SELECT id, repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language "
                f"FROM ast_symbols WHERE {repo_filter}(filepath LIKE ? OR filepath LIKE ?) ORDER BY start_line ASC",
                repo_params + [f"%/{clean_fp}", f"%\\{clean_fp}"]
            ).fetchall()

        routes = conn.execute(
            f"SELECT id, framework, http_method, path_pattern, handler_symbol, start_line, end_line "
            f"FROM api_routes WHERE {repo_filter}(filepath = ? OR filepath = ?)",
            repo_params + [clean_fp, f"/{clean_fp}"]
        ).fetchall()
        if not routes:
            routes = conn.execute(
                f"SELECT id, framework, http_method, path_pattern, handler_symbol, start_line, end_line "
                f"FROM api_routes WHERE {repo_filter}(filepath LIKE ? OR filepath LIKE ?)",
                repo_params + [f"%/{clean_fp}", f"%\\{clean_fp}"]
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

        sym_repo = sym["repo"]
        target_repo = sym_repo if repo != "__all__" else "__all__"
        repo_filter_clause = "" if target_repo == "__all__" else " AND r.repo = ?"
        repo_params = [] if target_repo == "__all__" else [target_repo]

        # 1. Fetch incoming callers:
        # Matches relationships where this symbol is called/used.
        # Never includes outgoing calls made by this symbol.
        # Resolves source_symbol_id from ast_symbols if missing, and groups multiple calls from same caller.
        callers_query = f"""
            SELECT 
                MIN(r.id) as id,
                COALESCE(r.source_symbol_id, src_sym.id) as source_symbol_id,
                r.source_filepath,
                r.source_symbol,
                r.target_symbol,
                r.relationship_type,
                MIN(r.line_number) as line_number,
                COUNT(*) as call_count,
                GROUP_CONCAT(DISTINCT r.line_number) as all_lines
            FROM ast_relationships r
            LEFT JOIN (
                SELECT id, repo, filepath, name, full_symbol,
                       ROW_NUMBER() OVER (PARTITION BY repo, filepath, name ORDER BY id ASC) as rn
                FROM ast_symbols
            ) src_sym ON (
                r.source_symbol_id = src_sym.id
                OR (r.source_symbol = src_sym.name AND (r.source_filepath = src_sym.filepath OR r.source_filepath LIKE '%/' || src_sym.filepath) AND r.repo = src_sym.repo)
            ) AND src_sym.rn = 1
            WHERE (r.target_symbol = ? OR (r.target_symbol = ? AND ? != '')){repo_filter_clause}
            GROUP BY r.source_filepath, r.source_symbol, r.relationship_type
            ORDER BY r.source_filepath, MIN(r.line_number) ASC
        """
        full_sym = sym["full_symbol"] or ""
        caller_params = [sym["name"], full_sym, full_sym] + repo_params
        callers = conn.execute(callers_query, caller_params).fetchall()

        # 2. Fetch outgoing dependencies (callees):
        # Matches calls originating from this symbol.
        # Resolves target_filepath and target_symbol_id from ast_symbols so links work across usages!
        # Groups repeated calls to the same target and sorts resolved codebase targets to the top.
        callees_query = f"""
            SELECT 
                MIN(r.id) as id,
                r.target_symbol,
                r.relationship_type,
                MIN(r.line_number) as line_number,
                COUNT(*) as call_count,
                GROUP_CONCAT(DISTINCT r.line_number) as all_lines,
                tgt_sym.filepath as target_filepath,
                tgt_sym.id as target_symbol_id
            FROM ast_relationships r
            LEFT JOIN (
                SELECT id, repo, filepath, name, full_symbol,
                       ROW_NUMBER() OVER (PARTITION BY repo, name ORDER BY id ASC) as rn
                FROM ast_symbols
            ) tgt_sym ON (
                (r.target_symbol = tgt_sym.name OR r.target_symbol = tgt_sym.full_symbol)
                AND (r.repo = tgt_sym.repo OR ? = '__all__')
                AND tgt_sym.rn = 1
            )
            WHERE (r.source_symbol_id = ? OR (r.source_symbol = ? AND (r.source_filepath = ? OR r.source_filepath LIKE ?)))
              AND r.relationship_type != 'IMPORTS'{repo_filter_clause}
            GROUP BY r.target_symbol, r.relationship_type
            ORDER BY 
                CASE WHEN tgt_sym.filepath IS NOT NULL THEN 0 ELSE 1 END ASC,
                MIN(r.line_number) ASC
        """
        callee_params = [target_repo, sym["id"], sym["name"], sym["filepath"], f"%/{_clean_path(sym['filepath'])}"] + repo_params
        callees = conn.execute(callees_query, callee_params).fetchall()

        # 3. Fetch imports:
        imports_query = f"""
            SELECT 
                MIN(r.id) as id, 
                r.target_symbol, 
                MIN(r.line_number) as line_number,
                COUNT(*) as import_count,
                GROUP_CONCAT(DISTINCT r.line_number) as all_lines
            FROM ast_relationships r
            WHERE (r.source_symbol_id = ? OR (r.source_symbol = ? AND (r.source_filepath = ? OR r.source_filepath LIKE ?)))
              AND r.relationship_type = 'IMPORTS'{repo_filter_clause}
            GROUP BY r.target_symbol
            ORDER BY MIN(r.line_number) ASC
        """
        import_params = [sym["id"], sym["name"], sym["filepath"], f"%/{_clean_path(sym['filepath'])}"] + repo_params
        imports = conn.execute(imports_query, import_params).fetchall()

        # 4. Fetch API route mapping:
        clean_sym_fp = _clean_path(sym["filepath"])
        route_repo_clause = "" if target_repo == "__all__" else " AND repo = ?"
        route_query = f"""
            SELECT framework, http_method, path_pattern 
            FROM api_routes 
            WHERE (handler_symbol = ? OR (filepath = ? OR filepath = ? OR filepath LIKE ?))
              AND start_line <= ? AND end_line >= ?{route_repo_clause}
        """
        route_params = [sym["name"], clean_sym_fp, f"/{clean_sym_fp}", f"%/{clean_sym_fp}", sym["start_line"], sym["end_line"]] + repo_params
        route = conn.execute(route_query, route_params).fetchone()

    return {
        "symbol": dict(sym),
        "route": dict(route) if route else None,
        "callers": [dict(c) for c in callers],
        "callees": [dict(c) for c in callees],
        "imports": [dict(i) for i in imports]
    }
