import os
import sys
from typing import Any, Callable, Dict, List, Optional

from app.services.database import get_db_connection


def _db_conn():
    nav_mod = sys.modules.get("app.services.navigator")
    fn = getattr(nav_mod, "get_db_connection", None) if nav_mod else None
    return (fn or get_db_connection)()


def query_navigator_tree(
    repo: str,
    clean_path_fn: Callable[[str, Optional[str]], str],
    path_parts_fn: Callable[[str, Optional[str]], List[str]],
) -> Optional[Dict[str, Any]]:
    with _db_conn() as conn:
        where = "" if repo == "__all__" else " WHERE repo = ?"
        params = [] if repo == "__all__" else [repo]

        file_rows = conn.execute(
            f"SELECT filepath, repo, doc_type, language FROM indexed_files{where} ORDER BY filepath",
            params,
        ).fetchall()

        if not file_rows and repo != "__all__":
            repo_exists = conn.execute(
                "SELECT 1 FROM git_repositories WHERE name = ? UNION SELECT 1 FROM indexed_paths WHERE repo = ?",
                (repo, repo),
            ).fetchone()
            if not repo_exists:
                return None

        sym_counts = {
            clean_path_fn(row["filepath"], repo=repo): row["cnt"]
            for row in conn.execute(
                f"SELECT filepath, count(*) as cnt FROM ast_symbols{where} GROUP BY filepath",
                params,
            ).fetchall()
        }
        route_counts = {
            clean_path_fn(row["filepath"], repo=repo): row["cnt"]
            for row in conn.execute(
                f"SELECT filepath, count(*) as cnt FROM api_routes{where} GROUP BY filepath",
                params,
            ).fetchall()
        }

    if repo == "__all__":
        sources: Dict[str, list] = {}
        for f in file_rows:
            sources.setdefault(f["repo"], []).append(f)

        root_children = {}
        for source_name, source_files in sorted(sources.items()):
            source_root = {"children": {}}
            for f in source_files:
                raw_path = clean_path_fn(f["filepath"], repo=f["repo"])
                parts = path_parts_fn(f["filepath"], repo=f["repo"])
                if not parts:
                    continue
                curr = source_root
                for i, part in enumerate(parts):
                    is_last = i == len(parts) - 1
                    rel_path = f"{source_name}/{'/'.join(parts[:i + 1])}"
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
            raw_path = clean_path_fn(f["filepath"], repo=f["repo"])
            parts = path_parts_fn(f["filepath"], repo=f["repo"])
            if not parts:
                continue
            curr = root
            for i, part in enumerate(parts):
                is_last = i == len(parts) - 1
                rel_path = "/".join(parts[:i + 1])
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
            node["symbol_count"] = sum(c["symbol_count"] for c in node["children"])
            node["route_count"] = sum(c["route_count"] for c in node["children"])
        return node

    tree = [_format_node(c) for c in root["children"].values()]
    return {
        "repo": repo,
        "total_files": len(file_rows),
        "total_symbols": sum(sym_counts.values()),
        "tree": tree,
    }


def query_omni_search(
    repo: str,
    query: str,
    limit: int,
    clean_path_fn: Callable[[str, Optional[str]], str],
) -> Dict[str, Any]:
    raw_query = (query or "").strip()
    if not raw_query:
        return {"query": "", "repo": repo, "total_matches": 0, "matches": []}

    matches: List[Dict[str, Any]] = []
    like_q = f"%{raw_query}%"
    lower_q = raw_query.lower()

    with _db_conn() as conn:
        repo_clause = "" if repo == "__all__" else " AND repo = ?"
        repo_params = [] if repo == "__all__" else [repo]

        sym_sql = f"""
            SELECT id, repo, filepath, name, full_symbol, kind, start_line, end_line, signature
            FROM ast_symbols
            WHERE (name LIKE ? OR full_symbol LIKE ? OR signature LIKE ?){repo_clause}
            LIMIT ?
        """
        for row in conn.execute(sym_sql, [like_q, like_q, like_q] + repo_params + [limit]).fetchall():
            sym_name = row["name"] or ""
            full_sym = row["full_symbol"] or sym_name
            sym_lower, full_lower = sym_name.lower(), full_sym.lower()

            if sym_lower == lower_q or full_lower == lower_q:
                score, label = 0.99, "99% AST exact match"
            elif sym_lower.startswith(lower_q) or full_lower.startswith(lower_q):
                score, label = 0.94, "94% AST prefix match"
            elif lower_q in sym_lower or lower_q in full_lower:
                score, label = 0.88, "88% AST symbol match"
            else:
                score, label = 0.82, "82% Signature match"

            matches.append({
                "id": f"sym_{row['id']}",
                "type": "symbol",
                "symbol_id": row["id"],
                "name": sym_name,
                "full_symbol": full_sym,
                "kind": row["kind"],
                "filepath": clean_path_fn(row["filepath"], None),
                "repo": row["repo"],
                "start_line": row["start_line"],
                "end_line": row["end_line"],
                "score": score,
                "score_label": label,
                "preview": row["signature"] or f"{row['kind']} {sym_name}",
            })

        file_sql = f"SELECT filepath, repo, doc_type, language FROM indexed_files WHERE filepath LIKE ?{repo_clause} LIMIT ?"
        for row in conn.execute(file_sql, [like_q] + repo_params + [limit]).fetchall():
            fp = clean_path_fn(row["filepath"], None)
            fname = os.path.basename(fp)
            fname_lower = fname.lower()
            if fname_lower == lower_q:
                score, label = 0.96, "96% Exact filename"
            elif fname_lower.startswith(lower_q):
                score, label = 0.92, "92% Filename prefix"
            else:
                score, label = 0.85, "85% Path substring"
            matches.append({
                "id": f"file_{fp}", "type": "file", "name": fname, "kind": "file",
                "filepath": fp, "repo": row["repo"], "start_line": 1, "end_line": 1,
                "score": score, "score_label": label, "preview": fp,
            })

        route_sql = f"""
            SELECT id, repo, filepath, framework, http_method, path_pattern, handler_symbol, start_line, end_line
            FROM api_routes
            WHERE (path_pattern LIKE ? OR handler_symbol LIKE ?){repo_clause}
            LIMIT ?
        """
        for row in conn.execute(route_sql, [like_q, like_q] + repo_params + [limit]).fetchall():
            pat = row["path_pattern"] or ""
            score = 0.95 if pat.lower() == lower_q else 0.89
            matches.append({
                "id": f"route_{row['id']}", "type": "route", "name": f"{row['http_method']} {pat}", "kind": "route",
                "filepath": clean_path_fn(row["filepath"], None), "repo": row["repo"],
                "start_line": row["start_line"], "end_line": row["end_line"],
                "score": score, "score_label": f"{int(score * 100)}% Route match",
                "preview": f"{row['http_method']} {pat} -> {row['handler_symbol'] or ''}",
            })

        try:
            chunk_sql = f"SELECT id, repo, filepath, chunk_text, start_line, end_line FROM code_chunks WHERE chunk_text LIKE ?{repo_clause} LIMIT ?"
            for row in conn.execute(chunk_sql, [like_q] + repo_params + [limit]).fetchall():
                preview = (row["chunk_text"] or "").strip().split("\n")[0][:120]
                matches.append({
                    "id": f"code_{row['id']}", "type": "code", "name": preview[:50], "kind": "code",
                    "filepath": clean_path_fn(row["filepath"], None), "repo": row["repo"],
                    "start_line": row["start_line"], "end_line": row["end_line"],
                    "score": 0.86, "score_label": "86% Code match", "preview": preview,
                })
        except Exception:
            pass

    matches.sort(key=lambda m: m["score"], reverse=True)
    final_matches = matches[:limit]
    return {"query": raw_query, "repo": repo, "total_matches": len(final_matches), "matches": final_matches}
