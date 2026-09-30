import os
import logging
from typing import Optional, Dict, Any, List
from app.services.database import get_db_connection

logger = logging.getLogger("contextcortex.navigator")

def _clean_path(p: str, repo: Optional[str] = None) -> str:
    cleaned = p.replace("\\", "/")
    if "://" in cleaned:
        cleaned = cleaned.split("://", 1)[1]
    if repo and cleaned.startswith(f"{repo}:"):
        cleaned = cleaned[len(repo) + 1:]
    return cleaned.strip("/")

def _path_parts(filepath: str, repo: Optional[str] = None) -> List[str]:
    cleaned = _clean_path(filepath, repo=repo)
    return [part for part in cleaned.split("/") if part.strip()]

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
            sym_counts[_clean_path(row["filepath"], repo=repo)] = row["cnt"]

        # Fetch route counts per file
        route_counts = {}
        for row in conn.execute(
            f"SELECT filepath, count(*) as cnt FROM api_routes{where} GROUP BY filepath",
            params
        ).fetchall():
            route_counts[_clean_path(row["filepath"], repo=repo)] = row["cnt"]

    # Build hierarchical tree
    if repo == "__all__":
        # Group files by repo source, each gets its own root node
        sources: Dict[str, list] = {}
        for f in file_rows:
            sources.setdefault(f["repo"], []).append(f)

        root_children = {}
        for source_name, source_files in sorted(sources.items()):
            source_root = {"children": {}}
            for f in source_files:
                raw_path = _clean_path(f["filepath"], repo=f["repo"])
                parts = _path_parts(f["filepath"], repo=f["repo"])
                if not parts:
                    continue
                curr = source_root
                for i, part in enumerate(parts):
                    is_last = (i == len(parts) - 1)
                    rel_path = f"{source_name}/{'/'.join(parts[:i+1])}"
                    if part not in curr["children"]:
                        curr["children"][part] = {
                            "id": f"{'file' if is_last else 'dir'}:{rel_path}",
                            "name": part,
                            "is_dir": not is_last,
                            "path": rel_path,
                            "abs_path": f["filepath"] if is_last else None,
                            "children": {} if not is_last else None,
                            "language": f["language"] if is_last else None,
                            "symbol_count": sym_counts.get(raw_path, 0) if is_last else 0,
                            "route_count": route_counts.get(raw_path, 0) if is_last else 0,
                        }
                    curr = curr["children"][part]
            root_children[source_name] = {
                "id": f"source:{source_name}",
                "name": source_name,
                "is_dir": True,
                "path": source_name,
                "children": source_root["children"],
                "language": None,
                "symbol_count": 0,
                "route_count": 0,
            }
        root = {"children": root_children}
    else:
        root = {"children": {}}
        for f in file_rows:
            raw_path = _clean_path(f["filepath"], repo=f["repo"])
            parts = _path_parts(f["filepath"], repo=f["repo"])
            if not parts:
                continue
            curr = root
            for i, part in enumerate(parts):
                is_last = (i == len(parts) - 1)
                rel_path = "/".join(parts[:i+1])
                if part not in curr["children"]:
                    curr["children"][part] = {
                        "id": f"{'file' if is_last else 'dir'}:{rel_path}",
                        "name": part,
                        "is_dir": not is_last,
                        "path": rel_path,
                        "abs_path": f["filepath"] if is_last else None,
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
            "abs_path": n.get("abs_path"),
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

        clean_sym_fp = _clean_path(sym["filepath"])

        # Check for child member symbols in the same file (e.g. methods of a class or members of a struct/interface)
        member_rows = conn.execute(
            """
            SELECT id, name, full_symbol
            FROM ast_symbols
            WHERE repo = ? 
              AND (filepath = ? OR filepath = ? OR filepath LIKE ?)
              AND start_line > ? AND end_line <= ? AND id != ?
            """,
            (sym["repo"], sym["filepath"], f"/{clean_sym_fp}", f"%/{clean_sym_fp}", sym["start_line"], sym["end_line"], sym["id"])
        ).fetchall()

        target_names = {sym["name"]}
        if sym["full_symbol"]:
            target_names.add(sym["full_symbol"])
        for m in member_rows:
            target_names.add(m["name"])
            if m["full_symbol"]:
                target_names.add(m["full_symbol"])
        target_names_list = list(target_names)

        exclude_source_names = list(target_names)
        exclude_source_ids = [sym["id"]] + [m["id"] for m in member_rows]

        # 1. Fetch incoming callers:
        # Matches relationships where this symbol (or any of its member methods) is called/used.
        # Excludes self-calls originating from within this symbol or its member methods.
        callers_placeholders = ",".join(["?"] * len(target_names_list))
        ex_name_placeholders = ",".join(["?"] * len(exclude_source_names))
        ex_id_placeholders = ",".join(["?"] * len(exclude_source_ids))

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
                OR ((r.source_symbol = src_sym.name OR r.source_symbol = src_sym.full_symbol) AND (r.source_filepath = src_sym.filepath OR r.source_filepath LIKE '%/' || src_sym.filepath) AND r.repo = src_sym.repo)
            ) AND src_sym.rn = 1
            WHERE r.target_symbol IN ({callers_placeholders})
              AND (r.source_symbol_id IS NULL OR r.source_symbol_id NOT IN ({ex_id_placeholders}))
              AND r.source_symbol NOT IN ({ex_name_placeholders})
              AND r.relationship_type != 'IMPORTS'{repo_filter_clause}
            GROUP BY r.source_filepath, r.source_symbol, r.relationship_type
            ORDER BY r.source_filepath, MIN(r.line_number) ASC
        """
        caller_params = target_names_list + exclude_source_ids + exclude_source_names + repo_params
        callers = conn.execute(callers_query, caller_params).fetchall()

        # 2. Fetch outgoing dependencies (callees):
        # Matches calls originating from this symbol or any of its member methods.
        callee_source_ids = [sym["id"]] + [m["id"] for m in member_rows]
        callee_source_names = list(target_names)
        src_id_placeholders = ",".join(["?"] * len(callee_source_ids))
        src_name_placeholders = ",".join(["?"] * len(callee_source_names))

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
            WHERE (r.source_symbol_id IN ({src_id_placeholders}) 
                   OR (r.source_symbol IN ({src_name_placeholders}) AND (r.source_filepath = ? OR r.source_filepath = ? OR r.source_filepath LIKE ?)))
              AND r.relationship_type != 'IMPORTS'{repo_filter_clause}
            GROUP BY r.target_symbol, r.relationship_type
            ORDER BY 
                CASE WHEN tgt_sym.filepath IS NOT NULL THEN 0 ELSE 1 END ASC,
                MIN(r.line_number) ASC
        """
        callee_params = [target_repo] + callee_source_ids + callee_source_names + [sym["filepath"], f"/{clean_sym_fp}", f"%/{clean_sym_fp}"] + repo_params
        callees = conn.execute(callees_query, callee_params).fetchall()

        # 3. Fetch imports:
        # Imports in codebases are module/file-level. Include both symbol-specific imports (if any) and containing file-level imports.
        imports_query = f"""
            SELECT 
                MIN(r.id) as id, 
                r.target_symbol, 
                MIN(r.line_number) as line_number,
                COUNT(*) as import_count,
                GROUP_CONCAT(DISTINCT r.line_number) as all_lines
            FROM ast_relationships r
            WHERE (r.source_symbol_id = ? 
                   OR (r.source_symbol = ? AND (r.source_filepath = ? OR r.source_filepath = ? OR r.source_filepath LIKE ?))
                   OR (r.source_filepath = ? OR r.source_filepath = ? OR r.source_filepath LIKE ?))
              AND r.relationship_type = 'IMPORTS'{repo_filter_clause}
            GROUP BY r.target_symbol
            ORDER BY MIN(r.line_number) ASC
        """
        import_params = [
            sym["id"],
            sym["name"], sym["filepath"], f"/{clean_sym_fp}", f"%/{clean_sym_fp}",
            sym["filepath"], f"/{clean_sym_fp}", f"%/{clean_sym_fp}"
        ] + repo_params
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


def get_omni_search(repo: str, query: str, limit: int = 25) -> Dict[str, Any]:
    raw_query = (query or "").strip()
    if not raw_query:
        return {
            "query": "",
            "repo": repo,
            "total_matches": 0,
            "matches": []
        }

    matches: List[Dict[str, Any]] = []
    like_q = f"%{raw_query}%"
    lower_q = raw_query.lower()

    with get_db_connection() as conn:
        repo_clause = "" if repo == "__all__" else " AND repo = ?"
        repo_params = [] if repo == "__all__" else [repo]

        # 1. Search AST Symbols
        sym_sql = f"""
            SELECT id, repo, filepath, name, full_symbol, kind, start_line, end_line, signature
            FROM ast_symbols
            WHERE (name LIKE ? OR full_symbol LIKE ?){repo_clause}
            LIMIT ?
        """
        sym_params = [like_q, like_q] + repo_params + [limit]
        for row in conn.execute(sym_sql, sym_params).fetchall():
            sym_name = row["name"] or ""
            sym_lower = sym_name.lower()

            if sym_lower == lower_q:
                score = 0.99
                label = "99% AST exact match"
            elif sym_lower.startswith(lower_q):
                score = 0.94
                label = "94% AST prefix match"
            else:
                score = 0.88
                label = "88% AST symbol match"

            preview = row["signature"] or f"{row['kind']} {sym_name}"
            matches.append({
                "id": f"sym_{row['id']}",
                "type": "symbol",
                "symbol_id": row["id"],
                "name": sym_name,
                "kind": row["kind"],
                "filepath": _clean_path(row["filepath"]),
                "repo": row["repo"],
                "start_line": row["start_line"],
                "end_line": row["end_line"],
                "score": score,
                "score_label": label,
                "preview": preview
            })

        # 2. Search File Paths
        file_sql = f"""
            SELECT filepath, repo, doc_type, language
            FROM indexed_files
            WHERE filepath LIKE ?{repo_clause}
            LIMIT ?
        """
        file_params = [like_q] + repo_params + [limit]
        for row in conn.execute(file_sql, file_params).fetchall():
            fp = _clean_path(row["filepath"])
            fname = os.path.basename(fp)
            fname_lower = fname.lower()

            if fname_lower == lower_q:
                score = 0.96
                label = "96% Exact filename"
            elif fname_lower.startswith(lower_q):
                score = 0.92
                label = "92% Filename prefix"
            else:
                score = 0.85
                label = "85% Path substring"

            matches.append({
                "id": f"file_{fp}",
                "type": "file",
                "name": fname,
                "kind": "file",
                "filepath": fp,
                "repo": row["repo"],
                "start_line": 1,
                "end_line": 1,
                "score": score,
                "score_label": label,
                "preview": fp
            })

        # 3. Search API Routes
        route_sql = f"""
            SELECT id, repo, filepath, framework, http_method, path_pattern, handler_symbol, start_line, end_line
            FROM api_routes
            WHERE (path_pattern LIKE ? OR handler_symbol LIKE ?){repo_clause}
            LIMIT ?
        """
        route_params = [like_q, like_q] + repo_params + [limit]
        for row in conn.execute(route_sql, route_params).fetchall():
            pat = row["path_pattern"] or ""
            score = 0.95 if pat.lower() == lower_q else 0.89
            matches.append({
                "id": f"route_{row['id']}",
                "type": "route",
                "name": f"{row['http_method']} {pat}",
                "kind": "route",
                "filepath": _clean_path(row["filepath"]),
                "repo": row["repo"],
                "start_line": row["start_line"],
                "end_line": row["end_line"],
                "score": score,
                "score_label": f"{int(score * 100)}% Route match",
                "preview": f"{row['http_method']} {pat} -> {row['handler_symbol'] or ''}"
            })

        # 4. Search Code Chunks if table exists
        try:
            chunk_sql = f"""
                SELECT id, repo, filepath, chunk_text, start_line, end_line
                FROM code_chunks
                WHERE chunk_text LIKE ?{repo_clause}
                LIMIT ?
            """
            chunk_params = [like_q] + repo_params + [limit]
            for row in conn.execute(chunk_sql, chunk_params).fetchall():
                text = (row["chunk_text"] or "").strip()
                preview = text.split("\n")[0][:120]
                matches.append({
                    "id": f"code_{row['id']}",
                    "type": "code",
                    "name": preview[:50],
                    "kind": "code",
                    "filepath": _clean_path(row["filepath"]),
                    "repo": row["repo"],
                    "start_line": row["start_line"],
                    "end_line": row["end_line"],
                    "score": 0.86,
                    "score_label": "86% Code match",
                    "preview": preview
                })
        except Exception:
            pass

    matches.sort(key=lambda m: m["score"], reverse=True)
    final_matches = matches[:limit]

    return {
        "query": raw_query,
        "repo": repo,
        "total_matches": len(final_matches),
        "matches": final_matches
    }

