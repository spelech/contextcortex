import logging
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

from app.services.chunking import match_route_and_call, normalize_path_pattern
from app.services.database import get_db_connection
from app.services.file_reader import get_file_reader_service
from app.services.git_manager import format_git_permalink
from app.services.search import execute_hybrid_search
from app.services.stack_trace_parser import (
    RE_COBOL_ABEND_FRAME, RE_COBOL_DIAG_FRAME, RE_COBOL_PARAGRAPH_FRAME,
    RE_CSHARP_FRAME, RE_EXCEPTION_NAME, RE_GENERIC_FRAME, RE_HTTP_ROUTE,
    RE_JAVA_FRAME, RE_NODE_AT_FRAME, RE_PYTHON_FRAME, RE_QUOTED_ERROR,
    RE_SYMBOL_CANDIDATE, _STOP_IDENTIFIERS, _clean_diag_path, _is_test_path,
    build_semantic_query as _build_semantic_query, candidate_path_suffixes,
    extract_diagnostic_signals, normalize_stack_path, parse_stack_frames,
)

logger = logging.getLogger("contextcortex.diagnostics")

MAX_RESOLVED_FRAMES = 15
MAX_SNIPPET_CHARS = 4000
MAX_CANDIDATE_CHARS = 3000
MAX_MATCHED_ROUTES = 15
MAX_MATCHED_SYMBOLS = 20


def _cobol_alt_filenames(filename: str) -> List[str]:
    lower = filename.lower()
    stem, dot, ext = lower.rpartition(".")
    if dot and ext in ("cbl", "cob", "cpy"):
        return [f"{stem}.cbl", f"{stem}.cob", f"{stem}.cpy"]
    return [lower]


def _get_callers_and_callees(
    conn,
    repo: Optional[str],
    symbol_name: str,
    enclosing_filepath: Optional[str] = None,
    enclosing_start_line: Optional[int] = None,
    enclosing_end_line: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Fetches immediate 1-hop callers (prioritizing production code over tests) and file/line-scoped callees."""
    if not symbol_name:
        return [], []
    short_sym = symbol_name.split(".")[-1] if "." in symbol_name else symbol_name
    effective_repo = repo if (repo and repo != "unknown") else None

    c_sql = (
        "SELECT repo, source_symbol, target_symbol, source_filepath, line_number "
        "FROM ast_relationships WHERE (target_symbol = ? OR target_symbol = ?)"
    )
    c_params: List[Any] = [symbol_name, short_sym]
    if "." not in symbol_name:
        # C# call targets can be stored with the receiver type (`ToolService.PublishInstance`).
        c_sql = c_sql[:-1] + " OR target_symbol LIKE ?)"
        c_params.append(f"%.{symbol_name}")
    if effective_repo:
        c_sql += " AND repo = ?"
        c_params.append(effective_repo)
    c_rows = conn.execute(c_sql + " LIMIT 80", c_params).fetchall()

    scored_callers, seen_callers = [], set()
    for r in c_rows:
        clean_fp = _clean_diag_path(r["source_filepath"])
        dedup_k = (r["repo"], r["source_symbol"], clean_fp, r["line_number"])
        if dedup_k in seen_callers:
            continue
        seen_callers.add(dedup_k)
        exact_target = 0 if r["target_symbol"] == symbol_name else 1
        scored_callers.append((
            (1 if _is_test_path(clean_fp) else 0, exact_target, clean_fp, r["line_number"]),
            {"repo": r["repo"], "symbol": r["source_symbol"], "file": clean_fp, "line": r["line_number"]},
        ))
    scored_callers.sort(key=lambda x: x[0])
    callers = [item[1] for item in scored_callers[:10]]

    ce_sql = (
        "SELECT repo, target_symbol, source_filepath, line_number "
        "FROM ast_relationships WHERE (source_symbol = ? OR source_symbol = ?)"
    )
    ce_params: List[Any] = [symbol_name, short_sym]
    if effective_repo:
        ce_sql += " AND repo = ?"
        ce_params.append(effective_repo)
    if enclosing_filepath:
        clean_enc = _clean_diag_path(enclosing_filepath).lower()
        ce_sql += (
            " AND (LOWER(REPLACE(source_filepath, '\\', '/')) = ? "
            "OR LOWER(REPLACE(source_filepath, '\\', '/')) LIKE ? "
            "OR LOWER(REPLACE(source_filepath, '\\', '/')) LIKE ?)"
        )
        ce_params.extend([clean_enc, f"%/{clean_enc}", f"%://{clean_enc}"])
    if enclosing_start_line is not None and enclosing_end_line is not None:
        ce_sql += " AND line_number >= ? AND line_number <= ?"
        ce_params.extend([enclosing_start_line, enclosing_end_line])
    ce_rows = conn.execute(ce_sql + " ORDER BY line_number ASC LIMIT 25", ce_params).fetchall()

    callees, seen_callees = [], set()
    for r in ce_rows:
        clean_fp = _clean_diag_path(r["source_filepath"])
        dedup_k = (r["target_symbol"], r["line_number"])
        if dedup_k in seen_callees:
            continue
        seen_callees.add(dedup_k)
        callees.append({"repo": r["repo"], "symbol": r["target_symbol"], "file": clean_fp, "line": r["line_number"]})
        if len(callees) >= 10:
            break
    return callers, callees


def _build_norm_path_clauses(alt_basenames: List[str]) -> Tuple[List[str], List[Any]]:
    clauses, params = [], []
    norm_col = "LOWER(REPLACE(filepath, '\\', '/'))"
    for bn in alt_basenames:
        clauses.extend([f"{norm_col} = ?", f"{norm_col} LIKE ?", f"{norm_col} LIKE ?"])
        params.extend([bn, f"%/{bn}", f"%://{bn}"])
    return clauses, params


def _find_symbol_enclosing(conn, repo: Optional[str], file_suffix: str, line_no: int) -> Optional[Dict[str, Any]]:
    suffixes = candidate_path_suffixes(file_suffix)
    if not suffixes:
        return None
    like_clauses, params = _build_norm_path_clauses(_cobol_alt_filenames(suffixes[-1]))
    sql = (
        "SELECT id, repo, filepath, name, full_symbol, kind, signature, start_line, end_line "
        f"FROM ast_symbols WHERE ({' OR '.join(like_clauses)}) AND start_line <= ? AND end_line >= ?"
    )
    params.extend([line_no, line_no])
    if repo and repo != "unknown":
        sql += " AND repo = ?"
        params.append(repo)
    rows = conn.execute(sql + " ORDER BY (end_line - start_line) ASC LIMIT 25", params).fetchall()
    if not rows:
        return None

    lower_suffixes = [s.lower() for s in suffixes]
    best_row, best_rank = None, (999, 999999)
    for r in rows:
        clean_fp = _clean_diag_path(r["filepath"]).lower()
        match_idx = next(
            (idx for idx, suf in enumerate(lower_suffixes) if clean_fp == suf or clean_fp.endswith(f"/{suf}")),
            len(lower_suffixes),
        )
        rank = (match_idx, int(r["end_line"]) - int(r["start_line"]))
        if rank < best_rank:
            best_rank, best_row = rank, r
    return dict(best_row) if best_row else dict(rows[0])


def _find_matching_indexed_file(conn, repo: Optional[str], parsed_path: str) -> Optional[Dict[str, Any]]:
    suffixes = candidate_path_suffixes(parsed_path)
    if not suffixes:
        return None
    alt_basenames = _cobol_alt_filenames(suffixes[-1])

    def _query_candidates(repo_filter: Optional[str]) -> List[Any]:
        clauses, q_params = _build_norm_path_clauses(alt_basenames)
        q_sql = f"SELECT filepath, repo, doc_type, language, commit_sha FROM indexed_files WHERE ({' OR '.join(clauses)})"
        if repo_filter:
            q_sql += " AND repo = ?"
            q_params.append(repo_filter)
        return conn.execute(q_sql + " LIMIT 30", q_params).fetchall()

    rows = _query_candidates(repo) or (_query_candidates(None) if repo else [])
    if not rows:
        return None

    lower_suffixes = [s.lower() for s in suffixes]
    best_row, best_idx = None, len(lower_suffixes) + 1
    for r in rows:
        clean_fp = _clean_diag_path(r["filepath"]).lower()
        for idx, suf in enumerate(lower_suffixes):
            if clean_fp == suf or clean_fp.endswith(f"/{suf}"):
                if idx < best_idx:
                    best_idx, best_row = idx, r
                break
    return dict(best_row) if best_row else dict(rows[0])


def resolve_stack_frames(
    frames: List[Dict[str, Any]],
    repo: Optional[str] = None,
    context_lines: int = 5,
) -> List[Dict[str, Any]]:
    """Resolves parsed stack frames to indexed files, code slices, and enclosing symbol relations."""
    resolved = []
    file_reader = get_file_reader_service()
    with get_db_connection() as conn:
        git_repos = {
            r["name"]: dict(r)
            for r in conn.execute("SELECT name, url, commit_sha, provider FROM git_repositories").fetchall()
        }
        for frame in frames[:MAX_RESOLVED_FRAMES]:
            raw_path, line_no = frame["path"], int(frame["line"])
            matched_file = _find_matching_indexed_file(conn, repo, raw_path)
            file_path = matched_file["filepath"] if matched_file else raw_path
            clean_file_path = _clean_diag_path(file_path)
            target_repo = matched_file["repo"] if matched_file else (repo or "unknown")

            enclosing = _find_symbol_enclosing(conn, target_repo, file_path, line_no)
            symbol_name = (enclosing["full_symbol"] or enclosing["name"]) if enclosing else (frame.get("function") or None)
            kind = enclosing.get("kind") if enclosing else None
            signature = enclosing.get("signature") if enclosing else None

            code_snippet = ""
            effective_repo = target_repo if target_repo != "unknown" else None
            for cand_path in OrderedDict.fromkeys([file_path, clean_file_path, *candidate_path_suffixes(clean_file_path)]):
                if not cand_path:
                    continue
                try:
                    read_res = file_reader.read_file(
                        path=cand_path,
                        repo=effective_repo,
                        start_line=max(1, line_no - context_lines),
                        end_line=line_no + context_lines,
                    )
                    code_snippet = (read_res.get("content") or "")[:MAX_SNIPPET_CHARS]
                    if code_snippet:
                        break
                except Exception as e:
                    logger.debug(f"Could not read code snippet for {cand_path}:{line_no}: {e}")

            permalink = None
            if target_repo in git_repos:
                g_info = git_repos[target_repo]
                permalink = format_git_permalink(
                    g_info["url"], g_info["commit_sha"], clean_file_path, line_no, line_no, provider=g_info.get("provider")
                )

            callers, callees = (
                _get_callers_and_callees(
                    conn, target_repo, symbol_name,
                    enclosing_filepath=clean_file_path,
                    enclosing_start_line=enclosing.get("start_line") if enclosing else None,
                    enclosing_end_line=enclosing.get("end_line") if enclosing else None,
                )
                if symbol_name
                else ([], [])
            )
            resolved.append({
                "repo": target_repo, "file": clean_file_path, "line": line_no,
                "symbol": symbol_name, "kind": kind, "signature": signature,
                "code": code_snippet, "permalink": permalink,
                "callers": callers, "callees": callees,
            })
    return resolved


def match_routes_and_callers(
    extracted_routes: List[Tuple[Optional[str], str]],
    repo: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Matches extracted route paths to api_routes and external api_client_calls."""
    if not extracted_routes:
        return []
    matched_results, seen = [], set()
    with get_db_connection() as conn:
        all_routes = conn.execute(
            "SELECT id, repo, filepath, http_method, path_pattern, handler_symbol, start_line, end_line FROM api_routes"
            + (" WHERE repo = ?" if repo else ""),
            ([repo] if repo else []),
        ).fetchall()
        all_calls = conn.execute(
            "SELECT id, repo, filepath, http_method, url_pattern, caller_symbol, line_number FROM api_client_calls"
        ).fetchall()

        for method, path in extracted_routes:
            norm_target = normalize_path_pattern(path)
            for r in all_routes:
                if _is_test_path(r["filepath"]) or (method and r["http_method"] not in ("ALL", method)):
                    continue
                if match_route_and_call(r["path_pattern"], norm_target) or match_route_and_call(norm_target, r["path_pattern"]):
                    route_key = (r["repo"], r["http_method"], r["path_pattern"])
                    if route_key in seen:
                        continue
                    seen.add(route_key)
                    raw_ext_callers = [
                        {"repo": c["repo"], "symbol": c["caller_symbol"], "file": _clean_diag_path(c["filepath"]), "line": c["line_number"]}
                        for c in all_calls
                        if match_route_and_call(r["path_pattern"], c["url_pattern"])
                    ]
                    raw_ext_callers.sort(key=lambda c: (1 if _is_test_path(c["file"]) else 0, c["file"], c["line"]))
                    matched_results.append({
                        "method": r["http_method"],
                        "path": r["path_pattern"],
                        "handler": {
                            "repo": r["repo"], "symbol": r["handler_symbol"],
                            "file": _clean_diag_path(r["filepath"]), "line": r["start_line"],
                        },
                        "external_callers": raw_ext_callers[:10],
                    })
                    if len(matched_results) >= MAX_MATCHED_ROUTES:
                        return matched_results
    return matched_results


def match_symbols_and_exceptions(
    exceptions: List[str],
    quoted_errors: List[str],
    repo: Optional[str] = None,
    candidate_symbols: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Matches extracted exception class names, symbol identifiers, and quoted error identifiers against ast_symbols."""
    matched, seen = [], set()
    extra_syms = candidate_symbols or []
    terms = list(OrderedDict.fromkeys(exceptions + extra_syms + [q for q in quoted_errors if len(q.split()) <= 3]))
    if not terms:
        return matched

    with get_db_connection() as conn:
        for term in terms:
            short_term = term.split(".")[-1] if "." in term else term
            sql = (
                "SELECT repo, name, full_symbol, kind, filepath, start_line, end_line FROM ast_symbols "
                "WHERE (LOWER(name) = LOWER(?) OR LOWER(full_symbol) = LOWER(?) OR LOWER(name) = LOWER(?) OR LOWER(full_symbol) = LOWER(?))"
            )
            params: List[Any] = [term, term, short_term, short_term]
            if repo:
                sql += " AND repo = ?"
                params.append(repo)
            rows = conn.execute(sql + " LIMIT 10", params).fetchall()
            rows_sorted = sorted(
                rows,
                key=lambda r: (
                    1 if _is_test_path(r["filepath"]) else 0,
                    0 if (r["full_symbol"] == term or r["name"] == term) else 1,
                ),
            )
            for r in rows_sorted[:5]:
                clean_fp = _clean_diag_path(r["filepath"])
                if _is_test_path(clean_fp):
                    continue
                key = (r["repo"], r["name"], clean_fp, r["start_line"])
                if key not in seen:
                    seen.add(key)
                    matched.append({
                        "repo": r["repo"], "symbol": r["full_symbol"] or r["name"],
                        "kind": r["kind"], "file": clean_fp, "lines": [r["start_line"], r["end_line"]],
                    })
                    if len(matched) >= MAX_MATCHED_SYMBOLS:
                        return matched
    return matched


def find_semantic_candidates(
    issue_text: str,
    repo: Optional[str] = None,
    limit: int = 5,
    signals: Optional[Dict[str, Any]] = None,
    frames: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Executes hybrid semantic+lexical search and enriches candidates with 1-hop callers/callees."""
    candidates = []
    if not issue_text or not issue_text.strip():
        return candidates
    query_str = _build_semantic_query(issue_text, signals or {}, frames or []) if (signals or frames) else issue_text[:2000]
    try:
        hits = execute_hybrid_search(query_text=query_str, doc_type="code", repo=repo, limit=limit)
    except Exception as e:
        logger.warning(f"Hybrid search failed in diagnostics: {e}")
        hits = []

    with get_db_connection() as conn:
        git_repos = {
            r["name"]: dict(r)
            for r in conn.execute("SELECT name, url, commit_sha, provider FROM git_repositories").fetchall()
        }
        for h in hits[:limit]:
            p = h.payload
            target_repo = p.get("repo") or repo or "unknown"
            file_path = _clean_diag_path(p.get("rel_path") or p.get("path") or "")
            start_l, end_l = p.get("start_line", 1), p.get("end_line", 1)
            sym = p.get("full_symbol") or p.get("symbol")

            permalink = p.get("permalink_url") or p.get("github_url")
            if permalink and "\\" in permalink:
                permalink = permalink.replace("\\", "/")
            if not permalink and target_repo in git_repos:
                g_info = git_repos[target_repo]
                permalink = format_git_permalink(
                    g_info["url"], g_info["commit_sha"], file_path, start_l, end_l, provider=g_info.get("provider")
                )

            callers, callees = [], []
            if sym:
                c_list, ce_list = _get_callers_and_callees(
                    conn, target_repo, sym, enclosing_filepath=file_path, enclosing_start_line=start_l, enclosing_end_line=end_l
                )
                callers = [c["symbol"] for c in c_list if c.get("symbol")]
                callees = [ce["symbol"] for ce in ce_list if ce.get("symbol")]

            score_val = float(h.score) if isinstance(getattr(h, "score", None), (int, float)) else 0.0
            candidates.append({
                "score": round(score_val, 4), "repo": target_repo, "file": file_path,
                "lines": [start_l, end_l], "symbol": sym, "kind": p.get("kind"),
                "signature": p.get("signature"), "content": (p.get("content") or "")[:MAX_CANDIDATE_CHARS],
                "permalink": permalink, "callers": callers, "callees": callees,
            })
    return candidates


def diagnose_issue(
    issue_text: str,
    repo: Optional[str] = None,
    context_lines: int = 5,
    limit: int = 5,
) -> Dict[str, Any]:
    """Main triage coordinator for stack trace, log, and bug triage across Python, C#, TS/JS, COBOL, Java, Go, Rust."""
    clamped_context = max(1, min(15, int(context_lines)))
    clamped_limit = max(1, min(20, int(limit)))

    safe_text = issue_text or ""
    parsed_frames = parse_stack_frames(safe_text)
    signals = extract_diagnostic_signals(safe_text)

    frame_symbols = []
    for f in parsed_frames:
        if f.get("function"):
            frame_symbols.append(f["function"])
        if f.get("program"):
            frame_symbols.append(f["program"])
    merged_candidate_symbols = list(OrderedDict.fromkeys(signals.get("symbols", []) + frame_symbols))

    return {
        "resolved_frames": resolve_stack_frames(parsed_frames, repo=repo, context_lines=clamped_context),
        "matched_routes": match_routes_and_callers(signals["routes"], repo=repo),
        "matched_symbols": match_symbols_and_exceptions(
            signals["exceptions"], signals["quoted_errors"], repo=repo, candidate_symbols=merged_candidate_symbols
        ),
        "semantic_candidates": find_semantic_candidates(
            issue_text=safe_text, repo=repo, limit=clamped_limit, signals=signals, frames=parsed_frames
        ),
    }


__all__ = [
    "RE_PYTHON_FRAME", "RE_CSHARP_FRAME", "RE_JAVA_FRAME", "RE_NODE_AT_FRAME",
    "RE_COBOL_PARAGRAPH_FRAME", "RE_COBOL_ABEND_FRAME", "RE_COBOL_DIAG_FRAME",
    "RE_GENERIC_FRAME", "RE_QUOTED_ERROR", "RE_EXCEPTION_NAME", "RE_SYMBOL_CANDIDATE",
    "RE_HTTP_ROUTE", "_STOP_IDENTIFIERS", "normalize_stack_path", "_clean_diag_path",
    "_is_test_path", "parse_stack_frames", "extract_diagnostic_signals",
    "resolve_stack_frames", "match_routes_and_callers", "match_symbols_and_exceptions",
    "find_semantic_candidates", "diagnose_issue",
]
