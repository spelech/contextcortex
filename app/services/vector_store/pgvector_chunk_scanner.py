import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import Engine, text

from app.services.code_grep_chunks import path_matches_filter

logger = logging.getLogger("contextcortex.vector_store.pgvector")

_PG_GREP_MAX_PAGES = 20
_LEADING_FLAGS_RE = re.compile(r"^\(\?([a-zA-Z]+)\)")


def _translate_python_regex_for_postgres(pattern: str) -> str:
    """Converts common Python regex escapes (`\\b`, `\\B`, `(?P<name>`) to newline-sensitive PostgreSQL ARE syntax."""
    out: List[str] = []
    in_class = False
    i = 0
    n = len(pattern)
    while i < n:
        ch = pattern[i]
        if ch == "\\" and i + 1 < n:
            nxt = pattern[i + 1]
            if not in_class and nxt == "b":
                out.append("\\y")
            elif not in_class and nxt == "B":
                out.append("\\Y")
            else:
                out.append(ch)
                out.append(nxt)
            i += 2
            continue
        if ch == "[" and not in_class:
            in_class = True
        elif ch == "]" and in_class:
            in_class = False
        elif not in_class and pattern.startswith("(?P<", i):
            gt = pattern.find(">", i + 4)
            if gt != -1:
                out.append("(?:")
                i = gt + 1
                continue
        out.append(ch)
        i += 1
    translated = "".join(out)
    # Enable PostgreSQL ARE newline-sensitive mode (?n) so ^ and $ match line boundaries (not chunk boundaries)
    # and '.' does not cross newlines, matching Python re.MULTILINE line-oriented grep semantics.
    lead = _LEADING_FLAGS_RE.match(translated)
    if lead:
        raw_flags = lead.group(1)
        pg_flags = "".join(dict.fromkeys("n" if f == "m" else f for f in raw_flags))
        if "n" not in pg_flags and "s" not in pg_flags and "p" not in pg_flags:
            pg_flags = "n" + pg_flags
        return f"(?{pg_flags}){translated[lead.end():]}"
    return f"(?n){translated}"


def _sql_path_prefilter(path_glob: Optional[str], is_sqlite: bool) -> Tuple[Optional[str], Dict[str, Any]]:
    """Builds a SQL LIKE prefilter for `path_glob` (always refined by Python `path_matches_filter`)."""
    if not path_glob:
        return None, {}
    norm = path_glob.replace("\\", "/").strip().strip("/")
    if not norm:
        return None, {}
    esc_char = "/" if is_sqlite else "\\"

    def _esc(s: str) -> str:
        return s.replace(esc_char, esc_char + esc_char).replace("%", esc_char + "%").replace("_", esc_char + "_")

    if any(c in norm for c in "*?["):
        if "[" in norm:
            return None, {}
        translated = _esc(norm.lower()).replace("*", "%").replace("?", "_")
        if "/" not in norm and not translated.startswith("%"):
            translated = f"%{translated}"
        like_val = translated
    else:
        like_val = f"%{_esc(norm.lower())}%"

    col = "LOWER(COALESCE(NULLIF(rel_path, ''), path, ''))" if not is_sqlite else "LOWER(COALESCE(rel_path, path, ''))"
    clause = f"{col} LIKE :path_like ESCAPE '{esc_char}'"
    return clause, {"path_like": like_val}


def parse_json_payload(raw_payload: Any) -> Dict[str, Any]:
    if isinstance(raw_payload, str):
        try:
            return json.loads(raw_payload)
        except Exception:
            return {}
    elif isinstance(raw_payload, dict):
        return raw_payload
    return {}


def hydrate_chunk_row(row: Any) -> Dict[str, Any]:
    p = parse_json_payload(row["payload"])
    if "content" not in p and row["content"]:
        p["content"] = row["content"]
    if "start_line" not in p and row["start_line"] is not None:
        p["start_line"] = row["start_line"]
    if "end_line" not in p and row["end_line"] is not None:
        p["end_line"] = row["end_line"]
    if "repo" not in p and row["repo"]:
        p["repo"] = row["repo"]
    if "path" not in p and row["path"]:
        p["path"] = row["path"]
    if "rel_path" not in p and row["rel_path"]:
        p["rel_path"] = row["rel_path"]
    return p


def _try_set_local(conn: Any, sql_stmt: str) -> bool:
    """Executes a transaction-local PostgreSQL SET LOCAL inside a savepoint so unsupported GUCs never abort."""
    try:
        if hasattr(conn, "begin_nested"):
            with conn.begin_nested():
                conn.execute(text(sql_stmt))
        else:
            conn.execute(text(sql_stmt))
        return True
    except Exception:
        return False


def execute_pgvector_dense_query(
    conn: Any,
    table_name: str,
    where_clause: str,
    params: Dict[str, Any],
    target_limit: int,
    has_filter: bool,
    is_pg_dialect: bool = True,
) -> List[Any]:
    """Runs an HNSW dense vector query with pgvector 0.8+ iterative scanning and ef_search tuning."""
    safe_limit = max(1, int(target_limit))
    ef_search = max(40, safe_limit * 4)
    iterative_ok = False
    if is_pg_dialect:
        iterative_ok = _try_set_local(conn, "SET LOCAL hnsw.iterative_scan = 'relaxed_order'")
        _try_set_local(conn, f"SET LOCAL hnsw.ef_search = {ef_search}")

    if iterative_ok:
        scan_limit = max(safe_limit, min(safe_limit * 2, 100))
        cte_sql = text(f"""
        WITH relaxed_results AS MATERIALIZED (
            SELECT id, (embedding <=> CAST(:query_vec AS vector)) AS distance, payload
            FROM {table_name}
            WHERE {where_clause}
            ORDER BY embedding <=> CAST(:query_vec AS vector)
            LIMIT :scan_limit
        )
        SELECT id, (1 - distance) AS score, payload
        FROM relaxed_results
        ORDER BY distance ASC
        LIMIT :target_limit;
        """)
        qparams = {**params, "scan_limit": scan_limit, "target_limit": safe_limit}
        return conn.execute(cte_sql, qparams).mappings().fetchall()

    direct_sql = text(f"""
    SELECT id, (1 - (embedding <=> CAST(:query_vec AS vector))) AS score, payload
    FROM {table_name}
    WHERE {where_clause}
    ORDER BY embedding <=> CAST(:query_vec AS vector)
    LIMIT :target_limit;
    """)
    qparams = {**params, "target_limit": safe_limit}
    rows = conn.execute(direct_sql, qparams).mappings().fetchall()
    if is_pg_dialect and has_filter and len(rows) < safe_limit:
        retry_ef = max(200, safe_limit * 10)
        if _try_set_local(conn, f"SET LOCAL hnsw.ef_search = {retry_ef}"):
            rows = conn.execute(direct_sql, qparams).mappings().fetchall()
    return rows


def _normalize_rel_path(path: str, repo: Optional[str]) -> str:
    clean_path = (path or "").replace("\x00", "").replace("\\", "/").strip("/")
    rel_path = clean_path.split("://", 1)[1] if "://" in clean_path else clean_path
    if repo and rel_path.startswith(f"{repo}/"):
        rel_path = rel_path[len(repo) + 1:]
    return rel_path


def execute_pgvector_file_chunks(
    engine: Engine,
    table_name: str,
    collection_name: str,
    path: str,
    repo: Optional[str] = None,
) -> List[Dict[str, Any]]:
    rel_path = _normalize_rel_path(path, repo)
    has_repo = bool(repo and repo not in ("__all__", "all"))

    fast_conds = ["collection_name = :collection_name", "rel_path = :rel_path"]
    fast_params: Dict[str, Any] = {"collection_name": collection_name, "rel_path": rel_path}
    if has_repo:
        fast_conds.append("repo = :repo")
        fast_params["repo"] = repo

    fast_sql = text(f"""
    SELECT payload, content, start_line, end_line, repo, path, rel_path
    FROM {table_name}
    WHERE {' AND '.join(fast_conds)}
    ORDER BY COALESCE(start_line, 0) ASC, COALESCE(end_line, 0) ASC;
    """)

    try:
        with engine.connect() as conn:
            rows = conn.execute(fast_sql, fast_params).mappings().fetchall()
            if not rows:
                esc_rel = rel_path.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                fb_conds = [
                    "collection_name = :collection_name",
                    "(path = :path OR rel_path = :path OR path = :rel_path OR REPLACE(path, '\\', '/') LIKE :path_suffix ESCAPE '\\')",
                ]
                fb_params: Dict[str, Any] = {
                    "collection_name": collection_name,
                    "rel_path": rel_path,
                    "path": (path or "").replace("\x00", ""),
                    "path_suffix": f"%://{repo}/{esc_rel}" if has_repo else f"%/{esc_rel}",
                }
                if has_repo:
                    fb_conds.append("repo = :repo")
                    fb_params["repo"] = repo
                fb_sql = text(f"""
                SELECT payload, content, start_line, end_line, repo, path, rel_path
                FROM {table_name}
                WHERE {' AND '.join(fb_conds)}
                ORDER BY COALESCE(start_line, 0) ASC, COALESCE(end_line, 0) ASC;
                """)
                rows = conn.execute(fb_sql, fb_params).mappings().fetchall()
        chunks = [hydrate_chunk_row(r) for r in rows]
        chunks.sort(key=lambda p: (p.get("start_line") or 0, p.get("end_line") or 0))
        return chunks
    except Exception as e:
        logger.error(f"Error fetching file chunks from PgVectorStore: {e}")
        return []


def execute_pgvector_files_chunks_batch(
    engine: Engine,
    table_name: str,
    collection_name: str,
    paths: List[Tuple[Optional[str], str]],
) -> Dict[Tuple[Optional[str], str], List[Dict[str, Any]]]:
    """Batch-fetches chunks for multiple (repo, rel_path) pairs using the (collection_name, repo, rel_path) index."""
    if not paths:
        return {}
    unique_pairs = list(dict.fromkeys(paths))
    by_repo: Dict[Optional[str], List[Tuple[str, str]]] = {}
    for req_repo, raw_p in unique_pairs:
        eff_repo = None if req_repo in (None, "", "__all__", "all") else req_repo
        rel_p = _normalize_rel_path(raw_p, eff_repo)
        by_repo.setdefault(eff_repo, []).append((raw_p, rel_p))

    out: Dict[Tuple[Optional[str], str], List[Dict[str, Any]]] = {pair: [] for pair in unique_pairs}
    try:
        with engine.connect() as conn:
            for eff_repo, entries in by_repo.items():
                rel_to_raws: Dict[str, List[str]] = {}
                for raw_p, rel_p in entries:
                    rel_to_raws.setdefault(rel_p, []).append(raw_p)
                rel_list = list(rel_to_raws.keys())
                placeholders = ", ".join(f":rp_{i}" for i in range(len(rel_list)))
                params: Dict[str, Any] = {"collection_name": collection_name}
                for i, rp in enumerate(rel_list):
                    params[f"rp_{i}"] = rp
                conds = ["collection_name = :collection_name", f"rel_path IN ({placeholders})"]
                if eff_repo is not None:
                    conds.append("repo = :repo")
                    params["repo"] = eff_repo
                sql = text(f"""
                SELECT payload, content, start_line, end_line, repo, path, rel_path
                FROM {table_name}
                WHERE {' AND '.join(conds)}
                ORDER BY rel_path ASC, COALESCE(start_line, 0) ASC, COALESCE(end_line, 0) ASC;
                """)
                rows = conn.execute(sql, params).mappings().fetchall()
                grouped: Dict[str, List[Dict[str, Any]]] = {}
                for r in rows:
                    c = hydrate_chunk_row(r)
                    rp_key = str(r["rel_path"] or c.get("rel_path") or "")
                    grouped.setdefault(rp_key, []).append(c)
                for rel_p, raw_list in rel_to_raws.items():
                    chunks = grouped.get(rel_p, [])
                    chunks.sort(key=lambda p: (p.get("start_line") or 0, p.get("end_line") or 0))
                    for raw_p in raw_list:
                        for req_repo, req_raw in unique_pairs:
                            norm_req = None if req_repo in (None, "", "__all__", "all") else req_repo
                            if norm_req == eff_repo and req_raw == raw_p:
                                out[(req_repo, raw_p)] = chunks

                # Only fall back to legacy path-suffix scan if the whole repo returned zero indexed rel_path hits.
                if not grouped:
                    for raw_p, _ in entries:
                        for req_repo, req_raw in unique_pairs:
                            norm_req = None if req_repo in (None, "", "__all__", "all") else req_repo
                            if norm_req == eff_repo and req_raw == raw_p and not out.get((req_repo, req_raw)):
                                out[(req_repo, req_raw)] = execute_pgvector_file_chunks(
                                    engine=engine, table_name=table_name, collection_name=collection_name,
                                    path=req_raw, repo=req_repo,
                                )
    except Exception as e:
        logger.error(f"Error batch-fetching file chunks from PgVectorStore: {e}")
    return out


def execute_pgvector_grep_chunks(
    engine: Engine,
    table_name: str,
    collection_name: str,
    pattern: str,
    repo: Optional[str] = None,
    path_glob: Optional[str] = None,
    is_regex: bool = False,
    case_sensitive: bool = False,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    clean_pattern = (pattern or "").replace("\x00", "")
    if not clean_pattern:
        return []

    flags = re.MULTILINE | (0 if case_sensitive else re.IGNORECASE)
    regex_pat = clean_pattern if is_regex else re.escape(clean_pattern)
    try:
        compiled = re.compile(regex_pat, flags)
    except re.error as e:
        raise ValueError(f"Invalid regular expression pattern: {e}") from e

    is_sqlite = getattr(engine.dialect, "name", "") == "sqlite"
    base_conditions = ["collection_name = :collection_name"]
    base_params: Dict[str, Any] = {"collection_name": collection_name}

    if repo and repo not in ("__all__", "all"):
        base_conditions.append("repo = :repo")
        base_params["repo"] = repo.replace("\x00", "")

    path_clause, path_params = _sql_path_prefilter(path_glob, is_sqlite=is_sqlite)
    if path_clause:
        base_conditions.append(path_clause)
        base_params.update(path_params)

    content_conditions = list(base_conditions)
    content_params = dict(base_params)
    used_pg_regex = False

    if not is_sqlite:
        if is_regex:
            op = "~" if case_sensitive else "~*"
            content_conditions.append(f"content {op} :pattern")
            content_params["pattern"] = _translate_python_regex_for_postgres(clean_pattern)
            used_pg_regex = True
        else:
            op = "LIKE" if case_sensitive else "ILIKE"
            escaped = clean_pattern.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            content_conditions.append(f"content {op} :pattern ESCAPE '\\'")
            content_params["pattern"] = f"%{escaped}%"
    elif not is_regex:
        escaped = clean_pattern.replace("/", "//").replace("%", "/%").replace("_", "/_")
        content_conditions.append("content LIKE :pattern ESCAPE '/'")
        content_params["pattern"] = f"%{escaped}%"

    page_size = max(limit * 4, 250)

    def _scan_with(conds: List[str], qparams: Dict[str, Any]) -> List[Dict[str, Any]]:
        order_col = "COALESCE(NULLIF(rel_path, ''), path, '')" if not is_sqlite else "COALESCE(rel_path, path, '')"
        query_sql = text(f"""
        SELECT payload, content, start_line, end_line, repo, path, rel_path
        FROM {table_name}
        WHERE {' AND '.join(conds)}
        ORDER BY {order_col} ASC, COALESCE(start_line, 0) ASC, id ASC
        LIMIT :fetch_limit OFFSET :fetch_offset;
        """)
        matched_chunks: List[Dict[str, Any]] = []
        with engine.connect() as conn:
            for page_idx in range(_PG_GREP_MAX_PAGES):
                run_params = {**qparams, "fetch_limit": page_size, "fetch_offset": page_idx * page_size}
                rows = conn.execute(query_sql, run_params).mappings().fetchall()
                if not rows:
                    break
                for r in rows:
                    p = hydrate_chunk_row(r)
                    chunk_path = p.get("rel_path") or p.get("path") or ""
                    if path_glob and not path_matches_filter(chunk_path, path_glob):
                        continue
                    content = p.get("content") or ""
                    if compiled.search(content):
                        matched_chunks.append(p)
                        if len(matched_chunks) >= limit:
                            return matched_chunks[:limit]
                if len(rows) < page_size:
                    break
        return matched_chunks[:limit]

    try:
        return _scan_with(content_conditions, content_params)
    except Exception as e:
        if used_pg_regex:
            logger.debug(f"Postgres regex prefilter failed ({e}); falling back to paged Python regex scan.")
            return _scan_with(base_conditions, base_params)
        logger.error(f"Error running grep_chunks on PgVectorStore: {e}")
        raise
