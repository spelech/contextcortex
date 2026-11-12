import fnmatch
import json
import logging
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple, Annotated
from pydantic import Field

from app.services.auth import enforce_tool_permission, Role, ForbiddenError
from app.services.database.connection import get_db_connection
from app.services.file_reader import get_file_reader_service
from app.services.git_manager import format_git_permalink

logger = logging.getLogger("contextcortex.mcp.grep")

_LINE_TRUNCATION_SUFFIX = "...[line truncated]"
_MAX_GREP_LINE_CHARS = 400
_IGNORED_GREP_DIRS = frozenset({
    ".git", ".hg", ".svn", ".venv", "venv", "env",
    "node_modules", "vendor", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".tox", "dist", "build",
    "target", "bin", "obj", ".next", ".nuxt", "coverage",
})


def _resolve_reader_factory():
    t_mod = sys.modules.get("app.mcp.tools")
    if t_mod and hasattr(t_mod, "get_file_reader_service"):
        return getattr(t_mod, "get_file_reader_service")
    f_mod = sys.modules.get("app.mcp.handlers.file_handlers")
    if f_mod and hasattr(f_mod, "get_file_reader_service"):
        return getattr(f_mod, "get_file_reader_service")
    return get_file_reader_service


def truncate_grep_line(text: Optional[str], max_chars: int = _MAX_GREP_LINE_CHARS) -> str:
    """Truncates matched or context lines exceeding 400 characters with a clear suffix."""
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    keep = max(1, max_chars - len(_LINE_TRUNCATION_SUFFIX))
    return text[:keep] + _LINE_TRUNCATION_SUFFIX


def _sanitize_match_lines(match: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = dict(match)
    sanitized["match_text"] = truncate_grep_line(sanitized.get("match_text"))
    raw_ctx = sanitized.get("context") or []
    sanitized["context"] = [
        {"line": item.get("line"), "text": truncate_grep_line(item.get("text"))}
        for item in raw_ctx
    ]
    return sanitized


def _scan_extended_matches(
    reader: Any,
    pattern: str,
    repo: Optional[str],
    path_glob: Optional[str],
    is_regex: bool,
    case_sensitive: bool,
    context_lines: int,
    max_needed: int,
) -> List[Dict[str, Any]]:
    """Collects matches when offset + max_results exceeds FileReaderService's 100-match cap."""
    flags = 0 if case_sensitive else re.IGNORECASE
    regex_str = pattern if is_regex else re.escape(pattern)
    try:
        compiled = re.compile(regex_str, flags)
    except re.error as exc:
        raise ValueError(f"Invalid regular expression pattern: {exc}") from exc

    clamped_ctx = max(0, min(10, int(context_lines)))
    effective_repo = None if repo in ("__all__", "", "all") else repo

    disk_files: List[Tuple[str, str, str]] = []
    for ip in reader._get_authorized_indexed_paths():
        r_name = ip.get("repo") or "local"
        if effective_repo and r_name != effective_repo:
            continue
        root_p = os.path.abspath(ip["path"])
        if os.path.isdir(root_p):
            for dirpath, dirnames, filenames in os.walk(root_p):
                dirnames[:] = [d for d in dirnames if d not in _IGNORED_GREP_DIRS]
                for fname in filenames:
                    full_p = os.path.join(dirpath, fname)
                    rel_p = os.path.relpath(full_p, root_p).replace("\\", "/")
                    disk_files.append((full_p, r_name, rel_p))
        elif os.path.isfile(root_p):
            disk_files.append((root_p, r_name, os.path.basename(root_p)))

    for r_name, r_dir in reader._get_authorized_persistent_repos().items():
        if effective_repo and r_name != effective_repo:
            continue
        if os.path.isdir(r_dir):
            for dirpath, dirnames, filenames in os.walk(r_dir):
                dirnames[:] = [d for d in dirnames if d not in _IGNORED_GREP_DIRS]
                for fname in filenames:
                    full_p = os.path.join(dirpath, fname)
                    rel_p = os.path.relpath(full_p, r_dir).replace("\\", "/")
                    disk_files.append((full_p, r_name, rel_p))

    if effective_repo in (None, "local_storage") and os.path.isdir(reader.storage_root):
        s_root = reader.storage_root
        for dirpath, dirnames, filenames in os.walk(s_root):
            dirnames[:] = [d for d in dirnames if d not in _IGNORED_GREP_DIRS]
            for fname in filenames:
                full_p = os.path.join(dirpath, fname)
                rel_p = os.path.relpath(full_p, s_root).replace("\\", "/")
                disk_files.append((full_p, "local_storage", rel_p))

    matches: List[Dict[str, Any]] = []
    seen_files = set()
    seen_keys = set()
    norm_glob = path_glob.replace("\\", "/") if path_glob else None

    for abs_p, r_name, rel_p in disk_files:
        if norm_glob and not (fnmatch.fnmatch(rel_p, norm_glob) or fnmatch.fnmatch(os.path.basename(rel_p), norm_glob)):
            continue
        if (r_name, rel_p) in seen_files:
            continue
        seen_files.add((r_name, rel_p))
        try:
            if not os.path.isfile(abs_p) or reader.is_binary_file(abs_p):
                continue
            with open(abs_p, "r", encoding="utf-8", errors="replace") as f:
                file_lines = f.read().splitlines()
        except Exception:
            continue

        for idx, line_str in enumerate(file_lines):
            line_no = idx + 1
            if compiled.search(line_str) and (r_name, rel_p, line_no) not in seen_keys:
                seen_keys.add((r_name, rel_p, line_no))
                s_ctx = max(0, idx - clamped_ctx)
                e_ctx = min(len(file_lines), idx + clamped_ctx + 1)
                matches.append({
                    "repo": r_name,
                    "file": rel_p,
                    "line": line_no,
                    "match_text": line_str,
                    "context": [{"line": c + 1, "text": file_lines[c]} for c in range(s_ctx, e_ctx)],
                })
                if len(matches) >= max_needed:
                    break
        if len(matches) >= max_needed:
            break

    git_repos: Dict[str, Dict[str, Any]] = {}
    try:
        with get_db_connection() as conn:
            for r in conn.execute("SELECT name, url, commit_sha, provider FROM git_repositories").fetchall():
                git_repos[r["name"]] = dict(r)
    except Exception:
        pass

    for m in matches:
        m["symbol"] = None
        m["kind"] = None
        g_info = git_repos.get(m["repo"])
        m["permalink"] = (
            format_git_permalink(g_info["url"], g_info.get("commit_sha"), m["file"], m["line"], m["line"], provider=g_info.get("provider"))
            if g_info and g_info.get("url") else None
        )
    return matches


async def handle_grep_code(
    pattern: Annotated[str, Field(description="Exact literal string or regular expression to match across source files (Python, TypeScript/JS/TSX, C#, COBOL, Go, Rust, Java, C/C++, Markdown, configs).")],
    repo: Annotated[Optional[str], Field(description="Optional repository name or 'local_storage' to scope search. Omit to scan all indexed sources.")] = None,
    path_glob: Annotated[Optional[str], Field(description="Optional fnmatch path filter (e.g. '*.py', '*.cs', or 'app/services/*').")] = None,
    is_regex: Annotated[bool, Field(description="Set True to evaluate pattern as a Python regular expression; False (default) matches literal text.")] = False,
    case_sensitive: Annotated[bool, Field(description="Set True for case-sensitive matching; False (default) ignores case.")] = False,
    context_lines: Annotated[int, Field(description="Surrounding context lines per match, clamped to 0..10 (default 2). Lines > 400 chars are truncated.")] = 2,
    limit: Annotated[int, Field(description="Alias for max_results: maximum matches per page, clamped to 1..100 (default 30).")] = 30,
    max_results: Annotated[Optional[int], Field(description="Maximum matched lines per page, clamped to 1..100 (default 30). Overrides limit when specified.")] = None,
    offset: Annotated[int, Field(description="0-based match offset for pagination (default 0). Advance by next_offset when has_more is True.")] = 0,
) -> str:
    """Deterministic literal and regex pattern search across indexed repositories with bounded line lengths and pagination."""
    try:
        enforce_tool_permission(Role.VIEWER)
        reader_fn = _resolve_reader_factory()
        reader = reader_fn()

        raw_max = max_results if max_results is not None else limit
        safe_limit = max(1, min(int(raw_max if raw_max is not None else 30), 100))
        safe_offset = max(0, int(offset if offset is not None else 0))
        safe_context = max(0, min(int(context_lines if context_lines is not None else 2), 10))
        needed = safe_offset + safe_limit + 1

        if needed <= 100:
            raw_result = reader.grep_code(
                pattern=pattern,
                repo=repo,
                path_glob=path_glob,
                is_regex=is_regex,
                case_sensitive=case_sensitive,
                context_lines=safe_context,
                limit=100,
            )
            all_matches = raw_result.get("matches", [])
        else:
            all_matches = _scan_extended_matches(
                reader=reader,
                pattern=pattern,
                repo=repo,
                path_glob=path_glob,
                is_regex=is_regex,
                case_sensitive=case_sensitive,
                context_lines=safe_context,
                max_needed=needed,
            )

        has_more = len(all_matches) > (safe_offset + safe_limit)
        page_slice = all_matches[safe_offset : safe_offset + safe_limit]
        sanitized_matches = [_sanitize_match_lines(m) for m in page_slice]
        next_offset = (safe_offset + safe_limit) if has_more else None

        payload = {
            "pattern": pattern,
            "total_matches": len(all_matches),
            "offset": safe_offset,
            "limit": safe_limit,
            "max_results": safe_limit,
            "has_more": has_more,
            "next_offset": next_offset,
            "truncated": has_more,
            "matches": sanitized_matches,
        }
        return json.dumps(payload, separators=(",", ":"))

    except ForbiddenError as fe:
        logger.warning(f"Forbidden error in handle_grep_code: {fe}")
        return json.dumps({"error": "forbidden", "message": str(fe)}, separators=(",", ":"))
    except ValueError as ve:
        return json.dumps({"error": "invalid_argument", "message": str(ve)}, separators=(",", ":"))
    except Exception as e:
        logger.error(f"Error searching code with grep: {e}")
        return json.dumps({"error": str(e)}, separators=(",", ":"))
