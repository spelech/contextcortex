import os
import logging
from typing import Optional, Dict, Any, List, Set
from app.services.db import get_db_connection
from app.services.topology.helpers import _clean_filepath, _get_permalink, _read_code_snippet

logger = logging.getLogger("contextcortex.topology")
import sys

def _get_conn():
    top_mod = sys.modules.get("app.services.topology")
    fn = getattr(top_mod, "get_db_connection", get_db_connection) if top_mod else get_db_connection
    return fn()


def get_node_details(node_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieves rich inspection details for a node:
    source snippet/signature, line ranges, permalinks, incoming and outgoing neighbors.
    """
    if not node_id:
        return None

    with _get_conn() as conn:
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
