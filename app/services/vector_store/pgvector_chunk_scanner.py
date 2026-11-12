import fnmatch
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional
from sqlalchemy import Engine, text

logger = logging.getLogger("contextcortex.vector_store.pgvector")


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
    conditions = ["collection_name = :collection_name"]
    params: Dict[str, Any] = {
        "collection_name": collection_name,
        "fetch_limit": max(limit * 4, 200),
    }

    if repo and repo not in ("__all__", "all"):
        conditions.append("repo = :repo")
        params["repo"] = repo.replace("\x00", "")

    if not is_sqlite:
        if is_regex:
            op = "~" if case_sensitive else "~*"
            conditions.append(f"content {op} :pattern")
            params["pattern"] = clean_pattern
        else:
            op = "LIKE" if case_sensitive else "ILIKE"
            escaped = clean_pattern.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            conditions.append(f"content {op} :pattern ESCAPE '\\'")
            params["pattern"] = f"%{escaped}%"
    elif not is_regex:
        escaped = clean_pattern.replace("/", "//").replace("%", "/%").replace("_", "/_")
        conditions.append("content LIKE :pattern ESCAPE '/'")
        params["pattern"] = f"%{escaped}%"

    query_sql = text(f"""
    SELECT payload, content, start_line, end_line, repo, path, rel_path
    FROM {table_name}
    WHERE {' AND '.join(conditions)}
    LIMIT :fetch_limit;
    """)

    try:
        with engine.connect() as conn:
            rows = conn.execute(query_sql, params).mappings().fetchall()

        matched_chunks: List[Dict[str, Any]] = []
        for r in rows:
            p = hydrate_chunk_row(r)
            chunk_path = p.get("rel_path") or p.get("path") or ""
            if path_glob:
                norm_p = chunk_path.replace("\\", "/")
                norm_glob = path_glob.replace("\\", "/")
                if not (fnmatch.fnmatch(norm_p, norm_glob) or fnmatch.fnmatch(os.path.basename(norm_p), norm_glob)):
                    continue

            content = p.get("content") or ""
            if compiled.search(content):
                matched_chunks.append(p)
                if len(matched_chunks) >= limit:
                    break
        return matched_chunks[:limit]
    except Exception as e:
        logger.error(f"Error running grep_chunks on PgVectorStore: {e}")
        raise
