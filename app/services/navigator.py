import logging
from typing import Any, Dict, List, Optional

from app.services.database import get_db_connection
from app.services.navigator_outline import query_navigator_tree, query_omni_search

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
    return query_navigator_tree(repo, _clean_path, _path_parts)


def get_file_outline(repo: str, filepath: str) -> Optional[Dict[str, Any]]:
    clean_fp = _clean_path(filepath)
    with get_db_connection() as conn:
        repo_filter = "" if repo == "__all__" else "repo = ? AND "
        repo_params = [] if repo == "__all__" else [repo]
        exact_repo_prefix = f"{repo}://{clean_fp}" if repo != "__all__" else clean_fp

        symbols = conn.execute(
            f"SELECT id, repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language "
            f"FROM ast_symbols WHERE {repo_filter}("
            f"REPLACE(filepath, '\\', '/') = ? OR REPLACE(filepath, '\\', '/') = ? OR REPLACE(filepath, '\\', '/') = ?"
            f") ORDER BY start_line ASC",
            repo_params + [clean_fp, f"/{clean_fp}", exact_repo_prefix],
        ).fetchall()

        if not symbols:
            symbols = conn.execute(
                f"SELECT id, repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language "
                f"FROM ast_symbols WHERE {repo_filter}("
                f"REPLACE(filepath, '\\', '/') LIKE ? OR REPLACE(filepath, '\\', '/') LIKE ?"
                f") ORDER BY start_line ASC",
                repo_params + [f"%/{clean_fp}", f"%://{clean_fp}"],
            ).fetchall()

        routes = conn.execute(
            f"SELECT id, framework, http_method, path_pattern, handler_symbol, start_line, end_line "
            f"FROM api_routes WHERE {repo_filter}("
            f"REPLACE(filepath, '\\', '/') = ? OR REPLACE(filepath, '\\', '/') = ? OR REPLACE(filepath, '\\', '/') = ?"
            f")",
            repo_params + [clean_fp, f"/{clean_fp}", exact_repo_prefix],
        ).fetchall()
        if not routes:
            routes = conn.execute(
                f"SELECT id, framework, http_method, path_pattern, handler_symbol, start_line, end_line "
                f"FROM api_routes WHERE {repo_filter}("
                f"REPLACE(filepath, '\\', '/') LIKE ? OR REPLACE(filepath, '\\', '/') LIKE ?"
                f")",
                repo_params + [f"%/{clean_fp}", f"%://{clean_fp}"],
            ).fetchall()

    route_by_handler = {r["handler_symbol"]: dict(r) for r in routes if r["handler_symbol"]}
    route_by_line = {r["start_line"]: dict(r) for r in routes}

    formatted_symbols = []
    seen_syms = set()
    for s in symbols:
        dedup_key = (s["name"], s["full_symbol"], s["kind"], s["start_line"], s["end_line"])
        if dedup_key in seen_syms:
            continue
        seen_syms.add(dedup_key)
        route_meta = (
            route_by_handler.get(s["full_symbol"])
            or route_by_handler.get(s["name"])
            or route_by_line.get(s["start_line"])
        )
        formatted_symbols.append({
            "id": s["id"],
            "name": s["name"],
            "full_symbol": s["full_symbol"],
            "kind": s["kind"],
            "start_line": s["start_line"],
            "end_line": s["end_line"],
            "signature": s["signature"],
            "language": s["language"],
            "route": route_meta,
        })

    return {"repo": repo, "filepath": clean_fp, "symbols": formatted_symbols}


def get_symbol_impact(repo: str, symbol_id: int) -> Optional[Dict[str, Any]]:
    with get_db_connection() as conn:
        sym = conn.execute(
            "SELECT id, repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language FROM ast_symbols WHERE id = ?",
            (symbol_id,),
        ).fetchone()
        if not sym:
            return None

        sym_repo = sym["repo"]
        target_repo = sym_repo if repo != "__all__" else "__all__"
        repo_filter_clause = "" if target_repo == "__all__" else " AND r.repo = ?"
        repo_params = [] if target_repo == "__all__" else [target_repo]
        clean_sym_fp = _clean_path(sym["filepath"])

        member_rows = conn.execute(
            """
            SELECT id, name, full_symbol
            FROM ast_symbols
            WHERE repo = ?
              AND (REPLACE(filepath, '\\', '/') = ? OR REPLACE(filepath, '\\', '/') = ? OR REPLACE(filepath, '\\', '/') LIKE ?)
              AND start_line > ? AND end_line <= ? AND id != ?
            """,
            (sym["repo"], sym["filepath"].replace("\\", "/"), f"/{clean_sym_fp}", f"%/{clean_sym_fp}", sym["start_line"], sym["end_line"], sym["id"]),
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

        callers_placeholders = ",".join(["?"] * len(target_names_list))
        ex_name_placeholders = ",".join(["?"] * len(exclude_source_names))
        ex_id_placeholders = ",".join(["?"] * len(exclude_source_ids))

        callers_query = f"""
            SELECT
                MIN(r.id) as id,
                MIN(COALESCE(r.source_symbol_id, src_sym.id)) as source_symbol_id,
                r.source_filepath,
                r.source_symbol,
                MIN(r.target_symbol) as target_symbol,
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
                OR ((r.source_symbol = src_sym.name OR r.source_symbol = src_sym.full_symbol)
                    AND (REPLACE(r.source_filepath, '\\', '/') = REPLACE(src_sym.filepath, '\\', '/')
                         OR REPLACE(r.source_filepath, '\\', '/') LIKE '%/' || REPLACE(src_sym.filepath, '\\', '/'))
                    AND r.repo = src_sym.repo)
            ) AND src_sym.rn = 1
            WHERE r.target_symbol IN ({callers_placeholders})
              AND (r.source_symbol_id IS NULL OR r.source_symbol_id NOT IN ({ex_id_placeholders}))
              AND r.source_symbol NOT IN ({ex_name_placeholders})
              AND r.relationship_type != 'IMPORTS'{repo_filter_clause}
            GROUP BY r.source_filepath, r.source_symbol, r.relationship_type
            ORDER BY r.source_filepath, MIN(r.line_number) ASC
        """
        callers = conn.execute(callers_query, target_names_list + exclude_source_ids + exclude_source_names + repo_params).fetchall()

        callee_source_ids = [sym["id"]] + [m["id"] for m in member_rows]
        callee_source_names = list(target_names)
        src_id_placeholders = ",".join(["?"] * len(callee_source_ids))
        src_name_placeholders = ",".join(["?"] * len(callee_source_names))
        join_repo_cond = "1=1" if target_repo == "__all__" else "r.repo = tgt_sym.repo"

        callees_query = f"""
            SELECT
                MIN(r.id) as id,
                r.target_symbol,
                r.relationship_type,
                MIN(r.line_number) as line_number,
                COUNT(*) as call_count,
                GROUP_CONCAT(DISTINCT r.line_number) as all_lines,
                MIN(tgt_sym.filepath) as target_filepath,
                MIN(tgt_sym.id) as target_symbol_id
            FROM ast_relationships r
            LEFT JOIN (
                SELECT id, repo, filepath, name, full_symbol,
                       ROW_NUMBER() OVER (PARTITION BY repo, name ORDER BY id ASC) as rn
                FROM ast_symbols
            ) tgt_sym ON (
                (r.target_symbol = tgt_sym.name OR r.target_symbol = tgt_sym.full_symbol)
                AND ({join_repo_cond})
                AND tgt_sym.rn = 1
            )
            WHERE (r.source_symbol_id IN ({src_id_placeholders})
                   OR (r.source_symbol IN ({src_name_placeholders})
                       AND (REPLACE(r.source_filepath, '\\', '/') = ? OR REPLACE(r.source_filepath, '\\', '/') = ? OR REPLACE(r.source_filepath, '\\', '/') LIKE ?)))
              AND r.relationship_type != 'IMPORTS'{repo_filter_clause}
            GROUP BY r.target_symbol, r.relationship_type
            ORDER BY
                CASE WHEN MIN(tgt_sym.filepath) IS NOT NULL THEN 0 ELSE 1 END ASC,
                MIN(r.line_number) ASC
        """
        callee_params = callee_source_ids + callee_source_names + [sym["filepath"].replace("\\", "/"), f"/{clean_sym_fp}", f"%/{clean_sym_fp}"] + repo_params
        callees = conn.execute(callees_query, callee_params).fetchall()

        imports_query = f"""
            SELECT
                MIN(r.id) as id,
                r.target_symbol,
                MIN(r.line_number) as line_number,
                COUNT(*) as import_count,
                GROUP_CONCAT(DISTINCT r.line_number) as all_lines
            FROM ast_relationships r
            WHERE (r.source_symbol_id = ?
                   OR (r.source_symbol = ? AND (REPLACE(r.source_filepath, '\\', '/') = ? OR REPLACE(r.source_filepath, '\\', '/') = ? OR REPLACE(r.source_filepath, '\\', '/') LIKE ?))
                   OR (REPLACE(r.source_filepath, '\\', '/') = ? OR REPLACE(r.source_filepath, '\\', '/') = ? OR REPLACE(r.source_filepath, '\\', '/') LIKE ?))
              AND r.relationship_type = 'IMPORTS'{repo_filter_clause}
            GROUP BY r.target_symbol
            ORDER BY MIN(r.line_number) ASC
        """
        norm_sym_fp = sym["filepath"].replace("\\", "/")
        import_params = [sym["id"], sym["name"], norm_sym_fp, f"/{clean_sym_fp}", f"%/{clean_sym_fp}", norm_sym_fp, f"/{clean_sym_fp}", f"%/{clean_sym_fp}"] + repo_params
        imports = conn.execute(imports_query, import_params).fetchall()

        route_repo_clause = "" if target_repo == "__all__" else " AND repo = ?"
        route_query = f"""
            SELECT framework, http_method, path_pattern
            FROM api_routes
            WHERE (handler_symbol = ? OR handler_symbol = ? OR (REPLACE(filepath, '\\', '/') = ? OR REPLACE(filepath, '\\', '/') = ? OR REPLACE(filepath, '\\', '/') LIKE ?))
              AND start_line <= ? AND end_line >= ?{route_repo_clause}
        """
        route_params = [sym["name"], sym["full_symbol"] or sym["name"], clean_sym_fp, f"/{clean_sym_fp}", f"%/{clean_sym_fp}", sym["start_line"], sym["end_line"]] + repo_params
        route = conn.execute(route_query, route_params).fetchone()

    sym_dict = dict(sym)
    if sym_dict.get("filepath"):
        sym_dict["filepath"] = _clean_path(sym_dict["filepath"])
    callers_list = []
    for c in callers:
        cd = dict(c)
        if cd.get("source_filepath"):
            cd["source_filepath"] = _clean_path(cd["source_filepath"])
        callers_list.append(cd)
    callees_list = []
    for c in callees:
        cd = dict(c)
        if cd.get("target_filepath"):
            cd["target_filepath"] = _clean_path(cd["target_filepath"])
        callees_list.append(cd)

    return {
        "symbol": sym_dict,
        "route": dict(route) if route else None,
        "callers": callers_list,
        "callees": callees_list,
        "imports": [dict(i) for i in imports],
    }


def get_omni_search(repo: str, query: str, limit: int = 25) -> Dict[str, Any]:
    return query_omni_search(repo, query, limit, _clean_path)
