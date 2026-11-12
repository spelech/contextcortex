import fnmatch
import logging
import os
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.services.git_manager import format_git_permalink

logger = logging.getLogger("contextcortex.file_reader")

IGNORED_GREP_DIRS = frozenset({
    ".git", ".hg", ".svn", ".venv", "venv", "env",
    "node_modules", "vendor", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".tox", "dist", "build",
    "target", "bin", "obj", ".next", ".nuxt", "coverage",
})


def execute_code_grep(
    pattern: str,
    storage_root: str,
    indexed_paths: List[Dict[str, Any]],
    persistent_repos: Dict[str, str],
    is_binary_fn: Callable[[str], bool],
    db_conn_factory: Callable[[], Any],
    repo: Optional[str] = None,
    path_glob: Optional[str] = None,
    is_regex: bool = False,
    case_sensitive: bool = False,
    context_lines: int = 2,
    limit: int = 30,
) -> Dict[str, Any]:
    """Searches files across disk, persistent clones, local storage, and vector store chunks with AST enrichment."""
    if not pattern or not isinstance(pattern, str) or not pattern.strip():
        raise ValueError("pattern must be a non-empty string")

    flags = 0 if case_sensitive else re.IGNORECASE
    regex_str = pattern if is_regex else re.escape(pattern)
    try:
        compiled = re.compile(regex_str, flags)
    except re.error as e:
        raise ValueError(f"Invalid regular expression pattern: {e}") from e

    clamped_context = max(0, min(10, int(context_lines)))
    clamped_limit = max(1, min(100, int(limit)))
    effective_repo = None if repo in ("__all__", "", "all") else repo

    git_repos: Dict[str, Dict[str, Any]] = {}
    try:
        with db_conn_factory() as conn:
            rows = conn.execute("SELECT name, url, commit_sha, provider FROM git_repositories").fetchall()
            for r in rows:
                git_repos[r["name"]] = dict(r)
    except Exception as e:
        logger.debug(f"Failed to load git repositories for permalinks: {e}")

    disk_files: List[Tuple[str, str, str]] = []

    # 1. Monitored indexed_paths
    for ip in indexed_paths:
        r_name = ip.get("repo") or "local"
        if effective_repo and r_name != effective_repo:
            continue
        root_p = os.path.abspath(ip["path"])
        if os.path.isdir(root_p):
            for dirpath, dirnames, filenames in os.walk(root_p):
                dirnames[:] = [d for d in dirnames if d not in IGNORED_GREP_DIRS]
                for fname in filenames:
                    full_p = os.path.join(dirpath, fname)
                    rel_p = os.path.relpath(full_p, root_p).replace("\\", "/")
                    disk_files.append((full_p, r_name, rel_p))
        elif os.path.isfile(root_p):
            disk_files.append((root_p, r_name, os.path.basename(root_p)))

    # 2. Persistent repos (keep_shallow=1)
    for r_name, r_dir in persistent_repos.items():
        if effective_repo and r_name != effective_repo:
            continue
        if os.path.isdir(r_dir):
            for dirpath, dirnames, filenames in os.walk(r_dir):
                dirnames[:] = [d for d in dirnames if d not in IGNORED_GREP_DIRS]
                norm_dp = dirpath.replace("\\", "/")
                if "/.git" in norm_dp or norm_dp.endswith("/.git"):
                    continue
                for fname in filenames:
                    full_p = os.path.join(dirpath, fname)
                    rel_p = os.path.relpath(full_p, r_dir).replace("\\", "/")
                    disk_files.append((full_p, r_name, rel_p))

    # 3. Local storage root
    if effective_repo in (None, "local_storage") and os.path.isdir(storage_root):
        for dirpath, dirnames, filenames in os.walk(storage_root):
            dirnames[:] = [d for d in dirnames if d not in IGNORED_GREP_DIRS]
            for fname in filenames:
                full_p = os.path.join(dirpath, fname)
                rel_p = os.path.relpath(full_p, storage_root).replace("\\", "/")
                disk_files.append((full_p, "local_storage", rel_p))

    def _matches_glob(path_str: str) -> bool:
        if not path_glob:
            return True
        norm_path = path_str.replace("\\", "/")
        norm_glob = path_glob.replace("\\", "/")
        return fnmatch.fnmatch(norm_path, norm_glob) or fnmatch.fnmatch(os.path.basename(norm_path), norm_glob)

    disk_files = [item for item in disk_files if _matches_glob(item[2])]

    matches: List[Dict[str, Any]] = []
    seen_keys = set()
    disk_scanned_keys = set()

    for abs_p, r_name, rel_p in disk_files:
        if (r_name, rel_p) in disk_scanned_keys:
            continue
        disk_scanned_keys.add((r_name, rel_p))

        try:
            if not os.path.isfile(abs_p) or is_binary_fn(abs_p):
                continue
            with open(abs_p, "r", encoding="utf-8", errors="replace") as f:
                file_text = f.read()
        except Exception:
            continue

        file_lines = file_text.splitlines()
        for line_idx, line_str in enumerate(file_lines):
            line_no = line_idx + 1
            if compiled.search(line_str):
                key = (r_name, rel_p, line_no)
                if key in seen_keys:
                    continue
                seen_keys.add(key)

                start_ctx = max(0, line_idx - clamped_context)
                end_ctx = min(len(file_lines), line_idx + clamped_context + 1)
                context_items = [
                    {"line": c_idx + 1, "text": file_lines[c_idx]}
                    for c_idx in range(start_ctx, end_ctx)
                ]
                matches.append({
                    "repo": r_name,
                    "file": rel_p,
                    "line": line_no,
                    "match_text": line_str,
                    "context": context_items,
                })
                if len(matches) >= clamped_limit:
                    break
        if len(matches) >= clamped_limit:
            break

    # 4. Vector store fallback for ephemeral / remote repos not on disk
    if len(matches) < clamped_limit:
        try:
            from app.services.vector_store import get_vector_store
            store = get_vector_store()
            if hasattr(store, "grep_chunks"):
                remaining_limit = (clamped_limit - len(matches)) * 5
                chunks = store.grep_chunks(
                    pattern=pattern,
                    repo=effective_repo,
                    path_glob=path_glob,
                    is_regex=is_regex,
                    case_sensitive=case_sensitive,
                    limit=max(10, remaining_limit),
                )
                for ch in chunks:
                    ch_repo = ch.get("repo") or "unknown"
                    raw_ch_file = (ch.get("rel_path") or ch.get("path") or "").replace("\\", "/")
                    ch_file = raw_ch_file.split("://", 1)[1] if "://" in raw_ch_file else raw_ch_file
                    if ch_file.startswith(f"{ch_repo}/"):
                        ch_file = ch_file[len(ch_repo) + 1:]

                    if (ch_repo, ch_file) in disk_scanned_keys:
                        continue

                    text_content = ch.get("content") or ch.get("text") or ""
                    start_line = int(ch.get("start_line") or 1)
                    ch_lines = text_content.splitlines()

                    for c_idx, line_str in enumerate(ch_lines):
                        curr_line = start_line + c_idx
                        if compiled.search(line_str):
                            key = (ch_repo, ch_file, curr_line)
                            if key in seen_keys:
                                continue
                            seen_keys.add(key)

                            start_ctx = max(0, c_idx - clamped_context)
                            end_ctx = min(len(ch_lines), c_idx + clamped_context + 1)
                            context_items = [
                                {"line": start_line + idx, "text": ch_lines[idx]}
                                for idx in range(start_ctx, end_ctx)
                            ]
                            matches.append({
                                "repo": ch_repo,
                                "file": ch_file,
                                "line": curr_line,
                                "match_text": line_str,
                                "context": context_items,
                            })
                            if len(matches) >= clamped_limit:
                                break
                    if len(matches) >= clamped_limit:
                        break
        except Exception as e:
            logger.warning(f"grep_chunks fallback in grep_code encountered error: {e}")

    # 5. AST symbol and permalink enrichment
    for m in matches:
        m_repo = m["repo"]
        m_file = m["file"].replace("\\", "/")
        m["file"] = m_file
        m_line = m["line"]

        sym_name = None
        sym_kind = None
        try:
            with db_conn_factory() as conn:
                row = conn.execute(
                    """
                    SELECT name, full_symbol, kind, start_line, end_line
                    FROM ast_symbols
                    WHERE repo = ?
                      AND (REPLACE(filepath, '\\', '/') = ? OR REPLACE(filepath, '\\', '/') LIKE ? OR REPLACE(filepath, '\\', '/') LIKE ?)
                      AND start_line <= ? AND end_line >= ?
                    ORDER BY (end_line - start_line) ASC
                    LIMIT 1
                    """,
                    (m_repo, m_file, f"%/{m_file}", f"%://{m_file}", m_line, m_line),
                ).fetchone()
                if row:
                    sym_name = row["full_symbol"] or row["name"]
                    sym_kind = row["kind"]
        except Exception as e:
            logger.debug(f"AST symbol lookup failed for {m_repo}:{m_file}:{m_line}: {e}")

        m["symbol"] = sym_name
        m["kind"] = sym_kind

        permalink = None
        g_info = git_repos.get(m_repo)
        if g_info and g_info.get("url"):
            permalink = format_git_permalink(
                g_info["url"],
                g_info.get("commit_sha"),
                m_file,
                m_line,
                m_line,
                provider=g_info.get("provider"),
            )
        m["permalink"] = permalink

    return {
        "pattern": pattern,
        "total_matches": len(matches),
        "truncated": len(matches) >= clamped_limit,
        "matches": matches,
    }
