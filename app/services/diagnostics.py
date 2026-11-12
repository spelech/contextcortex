import re
import logging
from typing import Optional, List, Dict, Any, Tuple
from collections import OrderedDict

from app.services.database import get_db_connection
from app.services.file_reader import get_file_reader_service
from app.services.git_manager import format_git_permalink
from app.services.chunking import match_route_and_call, normalize_path_pattern
from app.services.search import execute_hybrid_search

logger = logging.getLogger("contextcortex.diagnostics")

RE_PYTHON_FRAME = re.compile(
    r'File\s+["\'](?P<path>[^"\']+)["\'],\s+line\s+(?P<line>\d+)(?:,\s+in\s+(?P<func>[a-zA-Z0-9_<>\.]+))?',
    re.IGNORECASE
)
RE_NODE_AT_FRAME = re.compile(
    r'at\s+(?:(?P<func>[a-zA-Z0-9_<>\.]+)\s+\()?(?P<path>[^\s\(\):]+):(?P<line>\d+)(?::\d+)?\)?',
    re.IGNORECASE
)
RE_CSHARP_FRAME = re.compile(
    r'in\s+(?P<path>[^\s:]+\.cs):line\s+(?P<line>\d+)',
    re.IGNORECASE
)
RE_JAVA_FRAME = re.compile(
    r'at\s+(?P<pkg_class>[a-zA-Z0-9_\$]+(?:\.[a-zA-Z0-9_\$]+)*)\.(?P<method>[a-zA-Z0-9_<>\$]+)\((?P<filename>[a-zA-Z0-9_\-]+\.(?:java|kt)):(?P<line>\d+)\)',
    re.IGNORECASE
)
RE_GENERIC_FRAME = re.compile(
    r'(?:^|[\s\(\[\'\"])((?:[a-zA-Z0-9_.\-]+[/\\])+[a-zA-Z0-9_.\-]+(?:\.(?:go|rs|py|ts|js|jsx|tsx|cs|java|kt|c|cpp|h|hpp|rb|php))):(?P<line>\d+)(?::\d+)?',
    re.IGNORECASE | re.MULTILINE
)

RE_QUOTED_ERROR = re.compile(r'["\']([^"\'\r\n]{6,120})["\']')
RE_EXCEPTION_NAME = re.compile(r'\b[A-Z][A-Za-z0-9_]*(?:Error|Exception|Fault|Panic)\b')
RE_SYMBOL_CANDIDATE = re.compile(
    r'\b(?:[A-Z][A-Za-z0-9_]{2,}(?:\.[A-Za-z_][A-Za-z0-9_]{2,})+|[a-z][a-z0-9_]{1,}_[a-z0-9_]{2,}|[A-Z][a-z0-9]+[A-Z][A-Za-z0-9]+)\b'
)
RE_HTTP_ROUTE = re.compile(r'(?:(GET|POST|PUT|DELETE|PATCH)\s+)?(/[\w\-/{}:]+(?:/[\w\-/{}:]*)*)', re.IGNORECASE)

_STOP_IDENTIFIERS = {
    "RuntimeError", "ValueError", "TypeError", "KeyError", "AttributeError", "IndexError",
    "OperationalError", "DatabaseError", "IntegrityError", "HTTPException",
    "InvalidOperationException", "ArgumentException", "NullReferenceException",
    "Exception", "Error", "Traceback",
}


def _is_test_path(filepath: str) -> bool:
    norm = _clean_diag_path(filepath).lower()
    parts = [p for p in norm.split("/") if p]
    if any(p in ("tests", "test", "__tests__", "e2e", "spec", "specs") or p.endswith(".tests") or p.endswith("_tests") for p in parts):
        return True
    fname = parts[-1] if parts else ""
    return (
        fname.startswith("test_")
        or fname.endswith("_test.py")
        or fname.endswith(".test.ts")
        or fname.endswith(".test.tsx")
        or fname.endswith(".spec.ts")
        or fname.endswith("tests.cs")
    )


def parse_stack_frames(text: str) -> List[Dict[str, Any]]:
    """Parses stack frames across Python, JS/TS, C#, Java, Go/Rust/Generic formats."""
    frames, seen = [], set()
    for line in text.splitlines():
        trimmed = line.strip()
        if not trimmed:
            continue
        matched = False
        m_py = RE_PYTHON_FRAME.search(trimmed)
        if m_py:
            key = (m_py.group("path"), int(m_py.group("line")), m_py.group("func"))
            if key not in seen:
                seen.add(key)
                frames.append({"path": key[0], "line": key[1], "function": key[2]})
            matched = True
        if not matched:
            m_cs = RE_CSHARP_FRAME.search(trimmed)
            if m_cs:
                key = (m_cs.group("path"), int(m_cs.group("line")), None)
                if key not in seen:
                    seen.add(key)
                    frames.append({"path": key[0], "line": key[1], "function": None})
                matched = True
        if not matched:
            m_java = RE_JAVA_FRAME.search(trimmed)
            if m_java:
                pkg_c, meth = m_java.group("pkg_class"), m_java.group("method")
                fn = f"{pkg_c}.{meth}" if pkg_c and meth else (meth or pkg_c)
                key = (m_java.group("filename"), int(m_java.group("line")), fn)
                if key not in seen:
                    seen.add(key)
                    frames.append({"path": key[0], "line": key[1], "function": fn})
                matched = True
        if not matched:
            m_node = RE_NODE_AT_FRAME.search(trimmed)
            if m_node:
                key = (m_node.group("path"), int(m_node.group("line")), m_node.group("func"))
                if key not in seen:
                    seen.add(key)
                    frames.append({"path": key[0], "line": key[1], "function": key[2]})
                matched = True
        if not matched:
            m_gen = RE_GENERIC_FRAME.search(trimmed)
            if m_gen:
                key = (m_gen.group(1), int(m_gen.group("line")), None)
                if key not in seen:
                    seen.add(key)
                    frames.append({"path": key[0], "line": key[1], "function": None})
    return frames


def extract_diagnostic_signals(text: str) -> Dict[str, Any]:
    """Extracts quoted error strings, exception identifiers, code symbols, and HTTP routes."""
    errors, exceptions, symbols, routes = [], [], [], []
    seen_err, seen_exc, seen_sym, seen_routes = set(), set(), set(), set()
    for m in RE_QUOTED_ERROR.finditer(text):
        c = m.group(1).strip()
        if c and c not in seen_err:
            seen_err.add(c)
            errors.append(c)
    for m in RE_EXCEPTION_NAME.finditer(text):
        c = m.group(0).strip()
        if c and c not in seen_exc:
            seen_exc.add(c)
            exceptions.append(c)
    for m in RE_SYMBOL_CANDIDATE.finditer(text):
        c = m.group(0).strip()
        if c and c not in _STOP_IDENTIFIERS and c not in seen_exc and c not in seen_sym:
            seen_sym.add(c)
            symbols.append(c)
    for m in RE_HTTP_ROUTE.finditer(text):
        meth, p = (m.group(1).upper() if m.group(1) else None), m.group(2).strip()
        if len(p) > 1 and not p.endswith("//") and not p.startswith("//"):
            key = (meth, p)
            if key not in seen_routes:
                seen_routes.add(key)
                routes.append(key)
    return {"quoted_errors": errors, "exceptions": exceptions, "symbols": symbols, "routes": routes}


def _clean_diag_path(p: Optional[str]) -> str:
    if not p:
        return ""
    norm = p.replace("\\", "/")
    if "://" in norm:
        return norm.split("://", 1)[1]
    return norm


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
    if effective_repo:
        c_sql += " AND repo = ?"
        c_params.append(effective_repo)
    c_rows = conn.execute(c_sql + " LIMIT 80", c_params).fetchall()

    # Sort callers: exact full symbol match first, production files before test files
    scored_callers = []
    seen_callers = set()
    for r in c_rows:
        clean_fp = _clean_diag_path(r["source_filepath"])
        dedup_k = (r["repo"], r["source_symbol"], clean_fp, r["line_number"])
        if dedup_k in seen_callers:
            continue
        seen_callers.add(dedup_k)
        is_test = _is_test_path(clean_fp)
        exact_target = 0 if r["target_symbol"] == symbol_name else 1
        scored_callers.append((
            (1 if is_test else 0, exact_target, clean_fp, r["line_number"]),
            {"repo": r["repo"], "symbol": r["source_symbol"], "file": clean_fp, "line": r["line_number"]},
        ))
    scored_callers.sort(key=lambda x: x[0])
    callers = [item[1] for item in scored_callers[:10]]

    # Scope callees to the enclosing file and line range when known so generic method names (e.g. ExecuteAsync)
    # do not pull callees from unrelated classes with the same method name.
    ce_sql = "SELECT repo, target_symbol, source_filepath, line_number FROM ast_relationships WHERE (source_symbol = ? OR source_symbol = ?)"
    ce_params: List[Any] = [symbol_name, short_sym]
    if effective_repo:
        ce_sql += " AND repo = ?"
        ce_params.append(effective_repo)
    if enclosing_filepath:
        clean_enc = _clean_diag_path(enclosing_filepath)
        ce_sql += " AND (REPLACE(source_filepath, '\\', '/') = ? OR REPLACE(source_filepath, '\\', '/') LIKE ?)"
        ce_params.extend([clean_enc, f"%://{clean_enc}"])
    if enclosing_start_line is not None and enclosing_end_line is not None:
        ce_sql += " AND line_number >= ? AND line_number <= ?"
        ce_params.extend([enclosing_start_line, enclosing_end_line])
    ce_sql += " ORDER BY line_number ASC LIMIT 25"
    ce_rows = conn.execute(ce_sql, ce_params).fetchall()

    callees = []
    seen_callees = set()
    for r in ce_rows:
        clean_fp = _clean_diag_path(r["source_filepath"])
        dedup_k = (r["target_symbol"], r["line_number"])
        if dedup_k in seen_callees:
            continue
        seen_callees.add(dedup_k)
        callees.append({
            "repo": r["repo"],
            "symbol": r["target_symbol"],
            "file": clean_fp,
            "line": r["line_number"],
        })
        if len(callees) >= 10:
            break
    return callers, callees


def _find_symbol_enclosing(conn, repo: Optional[str], file_suffix: str, line_no: int) -> Optional[Dict[str, Any]]:
    norm_path = _clean_diag_path(file_suffix)
    sql = (
        "SELECT id, repo, filepath, name, full_symbol, kind, signature, start_line, end_line "
        "FROM ast_symbols "
        "WHERE (REPLACE(filepath, '\\', '/') = ? OR REPLACE(filepath, '\\', '/') LIKE ? OR REPLACE(filepath, '\\', '/') LIKE ?) "
        "AND start_line <= ? AND end_line >= ?"
    )
    params: List[Any] = [norm_path, f"%/{norm_path}", f"%{norm_path}", line_no, line_no]
    if repo and repo != "unknown":
        sql += " AND repo = ?"
        params.append(repo)
    sql += " ORDER BY (end_line - start_line) ASC LIMIT 1"
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None


def _find_matching_indexed_file(conn, repo: Optional[str], parsed_path: str) -> Optional[Dict[str, Any]]:
    norm_path = parsed_path.replace("\\", "/").lstrip("/")
    filename = norm_path.split("/")[-1]
    sql = (
        "SELECT filepath, repo, doc_type, language, commit_sha "
        "FROM indexed_files "
        "WHERE (REPLACE(filepath, '\\', '/') = ? OR REPLACE(filepath, '\\', '/') LIKE ? OR REPLACE(filepath, '\\', '/') LIKE ?)"
    )
    params: List[Any] = [norm_path, f"%/{norm_path}", f"%/{filename}"]
    if repo:
        sql += " AND repo = ?"
        params.append(repo)
    rows = conn.execute(sql + " LIMIT 20", params).fetchall()
    if rows:
        # Prefer exact suffix match on norm_path over basename-only match
        for r in rows:
            clean_fp = _clean_diag_path(r["filepath"])
            if clean_fp == norm_path or clean_fp.endswith(f"/{norm_path}"):
                return dict(r)
        return dict(rows[0])
    if not repo:
        row2 = conn.execute(
            "SELECT filepath, repo, doc_type, language, commit_sha FROM indexed_files WHERE REPLACE(filepath, '\\', '/') LIKE ? LIMIT 1",
            (f"%{filename}",)
        ).fetchone()
        if row2:
            return dict(row2)
    return None


def resolve_stack_frames(frames: List[Dict[str, Any]], repo: Optional[str] = None, context_lines: int = 5) -> List[Dict[str, Any]]:
    """Resolves parsed stack frames to indexed files, code slices, and enclosing symbol relations."""
    resolved, file_reader = [], get_file_reader_service()
    with get_db_connection() as conn:
        git_repos = {r["name"]: dict(r) for r in conn.execute("SELECT name, url, commit_sha, provider FROM git_repositories").fetchall()}
        for frame in frames:
            raw_path, line_no = frame["path"], frame["line"]
            matched_file = _find_matching_indexed_file(conn, repo, raw_path)
            file_path = matched_file["filepath"] if matched_file else raw_path
            clean_file_path = _clean_diag_path(file_path)
            target_repo = matched_file["repo"] if matched_file else (repo or "unknown")

            enclosing = _find_symbol_enclosing(conn, target_repo, file_path, line_no)
            symbol_name = (enclosing["full_symbol"] or enclosing["name"]) if enclosing else (frame.get("function") or None)
            kind = enclosing.get("kind") if enclosing else None
            signature = enclosing.get("signature") if enclosing else None

            code_snippet = ""
            try:
                read_res = file_reader.read_file(path=file_path, repo=target_repo if target_repo != "unknown" else None, start_line=max(1, line_no - context_lines), end_line=line_no + context_lines)
                code_snippet = read_res.get("content", "")
            except Exception as e:
                logger.debug(f"Could not read code snippet for {file_path}:{line_no}: {e}")

            permalink = None
            if target_repo in git_repos:
                g_info = git_repos[target_repo]
                permalink = format_git_permalink(g_info["url"], g_info["commit_sha"], clean_file_path, line_no, line_no, provider=g_info.get("provider"))

            callers, callees = (
                _get_callers_and_callees(
                    conn,
                    target_repo,
                    symbol_name,
                    enclosing_filepath=clean_file_path,
                    enclosing_start_line=enclosing.get("start_line") if enclosing else None,
                    enclosing_end_line=enclosing.get("end_line") if enclosing else None,
                )
                if symbol_name
                else ([], [])
            )
            resolved.append({
                "repo": target_repo, "file": clean_file_path, "line": line_no, "symbol": symbol_name,
                "kind": kind, "signature": signature, "code": code_snippet, "permalink": permalink,
                "callers": callers, "callees": callees
            })
    return resolved


def match_routes_and_callers(extracted_routes: List[Tuple[Optional[str], str]], repo: Optional[str] = None) -> List[Dict[str, Any]]:
    """Matches extracted route paths to api_routes and external api_client_calls."""
    matched_results, seen = [], set()
    with get_db_connection() as conn:
        all_routes = conn.execute("SELECT id, repo, filepath, http_method, path_pattern, handler_symbol, start_line, end_line FROM api_routes" + (" WHERE repo = ?" if repo else ""), ([repo] if repo else [])).fetchall()
        all_calls = conn.execute("SELECT id, repo, filepath, http_method, url_pattern, caller_symbol, line_number FROM api_client_calls").fetchall()

        for method, path in extracted_routes:
            norm_target = normalize_path_pattern(path)
            for r in all_routes:
                if _is_test_path(r["filepath"]):
                    continue
                if method and r["http_method"] not in ("ALL", method):
                    continue
                if match_route_and_call(r["path_pattern"], norm_target) or match_route_and_call(norm_target, r["path_pattern"]):
                    route_key = (r["repo"], r["http_method"], r["path_pattern"])
                    if route_key in seen:
                        continue
                    seen.add(route_key)
                    raw_ext_callers = [
                        {"repo": c["repo"], "symbol": c["caller_symbol"], "file": _clean_diag_path(c["filepath"]), "line": c["line_number"]}
                        for c in all_calls if match_route_and_call(r["path_pattern"], c["url_pattern"])
                    ]
                    raw_ext_callers.sort(key=lambda c: (1 if _is_test_path(c["file"]) else 0, c["file"], c["line"]))
                    matched_results.append({
                        "method": r["http_method"], "path": r["path_pattern"],
                        "handler": {"repo": r["repo"], "symbol": r["handler_symbol"], "file": _clean_diag_path(r["filepath"]), "line": r["start_line"]},
                        "external_callers": raw_ext_callers[:10]
                    })
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
            sql = "SELECT repo, name, full_symbol, kind, filepath, start_line, end_line FROM ast_symbols WHERE (name = ? OR full_symbol = ? OR full_symbol = ?)"
            params: List[Any] = [term, term, short_term]
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
                    matched.append({"repo": r["repo"], "symbol": r["full_symbol"] or r["name"], "kind": r["kind"], "file": clean_fp, "lines": [r["start_line"], r["end_line"]]})
    return matched


def _build_semantic_query(issue_text: str, signals: Dict[str, Any], frames: List[Dict[str, Any]]) -> str:
    """Strips boilerplate stack-trace file/line formatting so dense+BM25 hybrid search focuses on symbols and error messages."""
    parts: List[str] = []
    for f in frames:
        if f.get("function"):
            parts.append(str(f["function"]))
        if f.get("path"):
            parts.append(_clean_diag_path(str(f["path"])).split("/")[-1])
    parts.extend(signals.get("symbols", []))
    parts.extend(signals.get("exceptions", []))
    parts.extend(signals.get("quoted_errors", []))
    for _, route_path in signals.get("routes", []):
        parts.append(route_path)

    cleaned_lines = []
    for line in issue_text.splitlines():
        s = line.strip()
        if not s or s.startswith("Traceback (most recent call last)"):
            continue
        if RE_PYTHON_FRAME.search(s) or RE_CSHARP_FRAME.search(s) or RE_JAVA_FRAME.search(s):
            continue
        cleaned_lines.append(s)
    if cleaned_lines:
        parts.append(" ".join(cleaned_lines))

    dedup_tokens = list(OrderedDict.fromkeys(p for p in parts if p))
    return " ".join(dedup_tokens) if dedup_tokens else issue_text


def find_semantic_candidates(
    issue_text: str,
    repo: Optional[str] = None,
    limit: int = 5,
    signals: Optional[Dict[str, Any]] = None,
    frames: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Executes hybrid semantic+lexical search and enriches candidates with 1-hop callers/callees."""
    candidates = []
    if not issue_text.strip():
        return candidates
    query_str = _build_semantic_query(issue_text, signals or {}, frames or []) if (signals or frames) else issue_text
    try:
        hits = execute_hybrid_search(query_text=query_str, doc_type="code", repo=repo, limit=limit)
    except Exception as e:
        logger.warning(f"Hybrid search failed in diagnostics: {e}")
        hits = []

    with get_db_connection() as conn:
        git_repos = {r["name"]: dict(r) for r in conn.execute("SELECT name, url, commit_sha, provider FROM git_repositories").fetchall()}
        for h in hits:
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
                permalink = format_git_permalink(g_info["url"], g_info["commit_sha"], file_path, start_l, end_l, provider=g_info.get("provider"))

            callers, callees = [], []
            if sym:
                c_list, ce_list = _get_callers_and_callees(
                    conn,
                    target_repo,
                    sym,
                    enclosing_filepath=file_path,
                    enclosing_start_line=start_l,
                    enclosing_end_line=end_l,
                )
                callers = [c["symbol"] for c in c_list if c.get("symbol")]
                callees = [ce["symbol"] for ce in ce_list if ce.get("symbol")]

            score_val = float(h.score) if isinstance(getattr(h, "score", None), (int, float)) else 0.0
            candidates.append({
                "score": round(score_val, 4), "repo": target_repo, "file": file_path, "lines": [start_l, end_l],
                "symbol": sym, "kind": p.get("kind"), "signature": p.get("signature"),
                "content": p.get("content") or "", "permalink": permalink, "callers": callers, "callees": callees
            })
    return candidates


def diagnose_issue(issue_text: str, repo: Optional[str] = None, context_lines: int = 5, limit: int = 5) -> Dict[str, Any]:
    """Main triage coordinator for stack trace, log, and bug triage."""
    clamped_context = max(1, min(15, int(context_lines)))
    clamped_limit = max(1, min(20, int(limit)))

    parsed_frames = parse_stack_frames(issue_text)
    signals = extract_diagnostic_signals(issue_text)

    resolved_frames = resolve_stack_frames(parsed_frames, repo=repo, context_lines=clamped_context)
    matched_routes = match_routes_and_callers(signals["routes"], repo=repo)
    matched_symbols = match_symbols_and_exceptions(
        signals["exceptions"],
        signals["quoted_errors"],
        repo=repo,
        candidate_symbols=signals.get("symbols", []),
    )
    semantic_candidates = find_semantic_candidates(
        issue_text=issue_text,
        repo=repo,
        limit=clamped_limit,
        signals=signals,
        frames=parsed_frames,
    )

    return {
        "resolved_frames": resolved_frames,
        "matched_routes": matched_routes,
        "matched_symbols": matched_symbols,
        "semantic_candidates": semantic_candidates
    }
