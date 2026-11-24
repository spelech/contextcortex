import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import Engine, text

from app.services.code_grep_chunks import path_matches_filter

logger = logging.getLogger("contextcortex.vector_store.pgvector")

_PG_GREP_MAX_PAGES = 20


def _translate_python_regex_for_postgres(pattern: str) -> str:
    """Converts common Python regex escapes (`\\b`, `\\B`, `\\A`, `\\Z`, `(?P<name>`) to PostgreSQL ARE syntax."""
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
            elif not in_class and nxt == "A":
                out.append("^")
            elif not in_class and nxt == "Z":
                out.append("$")
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
    return "".join(out)


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


def execute_pgvector_file_chunks(
    engine: Engine,
    table_name: str,
    collection_name: str,
    path: str,
    repo: Optional[str] = None,
) -> List[Dict[str, Any]]:
    clean_path = (path or "").replace("\x00", "").replace("\\", "/").strip("/")
    rel_path = clean_path.split("://", 1)[1] if "://" in clean_path else clean_path
    if repo and rel_path.startswith(f"{repo}/"):
        rel_path = rel_path[len(repo) + 1:]

    esc_rel = rel_path.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    conditions = [
        "collection_name = :collection_name",
        "(rel_path = :rel_path OR path = :path OR rel_path = :path OR path = :rel_path OR REPLACE(path, '\\', '/') LIKE :path_suffix ESCAPE '\\')",
    ]
    params: Dict[str, Any] = {
        "collection_name": collection_name,
        "rel_path": rel_path,
        "path": (path or "").replace("\x00", ""),
        "path_suffix": f"%://{repo}/{esc_rel}" if (repo and repo not in ("__all__", "all")) else f"%/{esc_rel}",
    }
    if repo and repo not in ("__all__", "all"):
        conditions.append("repo = :repo")
        params["repo"] = repo

    query_sql = text(f"""
    SELECT payload, content, start_line, end_line, repo, path, rel_path
    FROM {table_name}
    WHERE {' AND '.join(conditions)}
    ORDER BY COALESCE(start_line, 0) ASC, COALESCE(end_line, 0) ASC;
    """)

    try:
        with engine.connect() as conn:
            rows = conn.execute(query_sql, params).mappings().fetchall()
        chunks = [hydrate_chunk_row(r) for r in rows]
        chunks.sort(key=lambda p: (p.get("start_line") or 0, p.get("end_line") or 0))
        return chunks
    except Exception as e:
        logger.error(f"Error fetching file chunks from PgVectorStore: {e}")
        return []


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

    flags = 0 if case_sensitive else re.IGNORECASE
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
