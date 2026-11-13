import fnmatch
import logging
import os
import re
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from app.services.code_grep_chunks import grep_chunk_matches
from app.services.git_manager import format_git_permalink
from app.services.ripgrep_runner import search_files_with_ripgrep
from app.services.text_decoding import read_source_text

logger = logging.getLogger("contextcortex.file_reader")

IGNORED_GREP_DIRS = frozenset({
    ".git", ".hg", ".svn", ".venv", "venv", "env",
    "node_modules", "vendor", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".tox", "dist", "build",
    "target", "bin", "obj", ".next", ".nuxt", "coverage",
})

_GLOB_CHARS = set("*?[")
# Regex syntax that is rare in literal search text: alternation, wildcards, classes, anchors, groups.
_REGEX_HINT = re.compile(r"\||\.\*|\.\+|\\[bdswBDSW]|\[[^\]]+\]|^\^|\$$|\(\?|\{\d+(,\d*)?\}")


def path_matches_filter(rel_path: str, path_filter: Optional[str]) -> bool:
    """
    True when `rel_path` matches the filter. A filter with wildcards is an fnmatch glob on the path or the
    file name ('*.cs', 'app/services/*'). A filter without wildcards is a file or folder: it matches the same
    path, anything below it, or a path that ends with it ('Services_V2', 'src/app/main.py', 'main.py').
    """
    if not path_filter:
        return True
    norm_path = rel_path.replace("\\", "/").strip("/")
    norm_filter = path_filter.replace("\\", "/").strip().strip("/")
    if not norm_filter:
        return True
    if _GLOB_CHARS & set(norm_filter):
        return fnmatch.fnmatch(norm_path, norm_filter) or fnmatch.fnmatch(os.path.basename(norm_path), norm_filter)
    path_l, filter_l = norm_path.lower(), norm_filter.lower()
    return (
        path_l == filter_l
        or path_l.startswith(filter_l + "/")
        or path_l.endswith("/" + filter_l)
        or f"/{filter_l}/" in f"/{path_l}/"
    )


def looks_like_regex(pattern: str) -> bool:
    """True when a pattern uses regex syntax (for example `A|B` or `foo.*bar`) and compiles as a regex."""
    if not pattern or not _REGEX_HINT.search(pattern):
        return False
    try:
        re.compile(pattern)
    except re.error:
        return False
    return True


def _collect_target_roots(
    storage_root: str,
    indexed_paths: List[Dict[str, Any]],
    persistent_repos: Dict[str, str],
    effective_repo: Optional[str],
) -> List[Tuple[str, str]]:
    roots: List[Tuple[str, str]] = []
    for ip in indexed_paths:
        r_name = ip.get("repo") or "local"
        if effective_repo and r_name != effective_repo:
            continue
        root_p = os.path.abspath(ip["path"])
        if os.path.exists(root_p):
            roots.append((root_p, r_name))

    for r_name, r_dir in persistent_repos.items():
        if effective_repo and r_name != effective_repo:
            continue
        if os.path.exists(r_dir):
            roots.append((os.path.abspath(r_dir), r_name))

    if effective_repo in (None, "local_storage") and os.path.isdir(storage_root):
        roots.append((os.path.abspath(storage_root), "local_storage"))

    return roots


def _scan_root_with_python(
    root_path: str,
    repo_name: str,
    compiled: re.Pattern,
    is_binary_fn: Callable[[str], bool],
    path_glob: Optional[str],
    context_lines: int,
    max_matches: int,
    seen_files: Set[Tuple[str, str]],
) -> List[Dict[str, Any]]:
    """Pure-Python fallback when ripgrep binary is unavailable or cannot handle an expression."""
    disk_files: List[Tuple[str, str]] = []
    if os.path.isfile(root_path):
        disk_files.append((root_path, os.path.basename(root_path)))
    elif os.path.isdir(root_path):
        for dirpath, dirnames, filenames in os.walk(root_path):
            dirnames[:] = [d for d in dirnames if d not in IGNORED_GREP_DIRS]
            norm_dp = dirpath.replace("\\", "/")
            if "/.git" in norm_dp or norm_dp.endswith("/.git"):
                continue
            for fname in filenames:
                full_p = os.path.join(dirpath, fname)
                rel_p = os.path.relpath(full_p, root_path).replace("\\", "/")
                disk_files.append((full_p, rel_p))

    out: List[Dict[str, Any]] = []
    for abs_p, rel_p in disk_files:
        if not path_matches_filter(rel_p, path_glob):
            continue
        if (repo_name, rel_p) in seen_files:
            continue
        seen_files.add((repo_name, rel_p))
        try:
            if not os.path.isfile(abs_p) or is_binary_fn(abs_p):
                continue
            file_lines = read_source_text(abs_p).splitlines()
        except Exception:
            continue

        for line_idx, line_str in enumerate(file_lines):
            if compiled.search(line_str):
                start_ctx = max(0, line_idx - context_lines)
                end_ctx = min(len(file_lines), line_idx + context_lines + 1)
                out.append({
                    "repo": repo_name,
                    "file": rel_p,
                    "line": line_idx + 1,
                    "match_text": line_str,
                    "context": [
                        {"line": c_idx + 1, "text": file_lines[c_idx]}
                        for c_idx in range(start_ctx, end_ctx)
                    ],
                })
                if len(out) >= max_matches:
                    return out
    return out


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
    max_limit: int = 100,
) -> Dict[str, Any]:
    """Searches files via ripgrep (with Python fallback) and ephemeral vector chunks, plus AST/permalink enrichment."""
    if not pattern or not isinstance(pattern, str) or not pattern.strip():
        raise ValueError("pattern must be a non-empty string")

    flags = 0 if case_sensitive else re.IGNORECASE
    regex_str = pattern if is_regex else re.escape(pattern)
    try:
        compiled = re.compile(regex_str, flags)
    except re.error as e:
        raise ValueError(f"Invalid regular expression pattern: {e}") from e

    clamped_context = max(0, min(10, int(context_lines)))
    upper_limit = max(100, int(max_limit))
    clamped_limit = max(1, min(upper_limit, int(limit)))
    effective_repo = None if repo in ("__all__", "", "all") else repo

    git_repos: Dict[str, Dict[str, Any]] = {}
    try:
        with db_conn_factory() as conn:
            rows = conn.execute("SELECT name, url, commit_sha, provider FROM git_repositories").fetchall()
            for r in rows:
                git_repos[r["name"]] = dict(r)
    except Exception as e:
        logger.debug(f"Failed to load git repositories for permalinks: {e}")

    roots = _collect_target_roots(storage_root, indexed_paths, persistent_repos, effective_repo)
    matches: List[Dict[str, Any]] = []
    seen_keys: Set[Tuple[str, str, int]] = set()
    seen_files: Set[Tuple[str, str]] = set()
    repo_root_dirs: Dict[str, List[str]] = {}
    for rp, rn in roots:
        if os.path.isdir(rp):
            repo_root_dirs.setdefault(rn, []).append(rp)

    for root_p, r_name in roots:
        if len(matches) >= clamped_limit:
            break
        remaining = clamped_limit - len(matches)
        rg_hits = search_files_with_ripgrep(
            root_dir=root_p,
            repo_name=r_name,
            pattern=pattern,
            ignored_dirs=IGNORED_GREP_DIRS,
            path_glob=path_glob,
            is_regex=is_regex,
            case_sensitive=case_sensitive,
            context_lines=clamped_context,
            max_matches=remaining + 10,
            include_hidden=True,
        )
        if rg_hits is None:
            py_hits = _scan_root_with_python(
                root_path=root_p,
                repo_name=r_name,
                compiled=compiled,
                is_binary_fn=is_binary_fn,
                path_glob=path_glob,
                context_lines=clamped_context,
                max_matches=remaining,
                seen_files=seen_files,
            )
            for item in py_hits:
                key = (item["repo"], item["file"], item["line"])
                if key not in seen_keys:
                    seen_keys.add(key)
                    matches.append(item)
                    if len(matches) >= clamped_limit:
                        break
            continue

        for item in rg_hits:
            rel_p = item["file"]
            abs_p = item.get("abs_path")
            seen_files.add((r_name, rel_p))
            if abs_p:
                try:
                    if not os.path.isfile(abs_p) or is_binary_fn(abs_p):
                        continue
                except OSError:
                    continue
            key = (r_name, rel_p, item["line"])
            if key in seen_keys:
                continue
            seen_keys.add(key)
            matches.append({
                "repo": r_name,
                "file": rel_p,
                "line": item["line"],
                "match_text": item["match_text"],
                "context": item["context"],
            })
            if len(matches) >= clamped_limit:
                break

    # Vector store fallback for ephemeral / remote repos not on disk
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
                from app.services.code_grep_chunks import chunk_file_key
                skip_files = set(seen_files)
                for ch in chunks:
                    ch_repo, ch_file = chunk_file_key(ch)
                    if any(os.path.isfile(os.path.join(rd, ch_file)) for rd in repo_root_dirs.get(ch_repo, ())):
                        skip_files.add((ch_repo, ch_file))
                load_fn = None
                if hasattr(store, "get_file_chunks"):
                    load_fn = lambda r_name, r_file: store.get_file_chunks(path=r_file, repo=r_name)
                matches.extend(grep_chunk_matches(
                    chunks=chunks,
                    compiled=compiled,
                    context_lines=clamped_context,
                    limit=clamped_limit - len(matches),
                    skip_files=skip_files,
                    seen_keys=seen_keys,
                    load_file_chunks=load_fn,
                ))
        except Exception as e:
            logger.warning(f"grep_chunks fallback in grep_code encountered error: {e}")

    # AST symbol and permalink enrichment
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
