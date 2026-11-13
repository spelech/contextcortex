import json
import logging
import sys
from typing import Annotated, Any, Dict, List, Optional
from pydantic import Field

from app.services.auth import ForbiddenError, Role, enforce_tool_permission
from app.services.code_grep_scanner import execute_code_grep, looks_like_regex
from app.services.database.connection import get_db_connection
from app.services.file_reader import get_file_reader_service

logger = logging.getLogger("contextcortex.mcp.grep")

_LINE_TRUNCATION_SUFFIX = "...[line truncated]"
_MAX_GREP_LINE_CHARS = 400


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


def _context_line_numbers(match: Dict[str, Any], raw_ctx: List[Dict[str, Any]]) -> List[Any]:
    """
    Line numbers for the context block. Numbers that do not go up line by line (for example the same number on every
    line) are replaced: the context line with the match text gets the match line, and the other lines count from it.
    """
    numbers = [item.get("line") for item in raw_ctx]
    if all(isinstance(n, int) for n in numbers) and all(b > a for a, b in zip(numbers, numbers[1:])):
        return numbers
    match_line = match.get("line")
    if not isinstance(match_line, int):
        return numbers
    texts = [item.get("text") for item in raw_ctx]
    anchor = next((i for i, (n, t) in enumerate(zip(numbers, texts)) if n == match_line and t == match.get("match_text")), None)
    if anchor is None:
        anchor = next((i for i, t in enumerate(texts) if t == match.get("match_text")), None)
    if anchor is None:
        return numbers
    return [match_line - anchor + i for i in range(len(raw_ctx))]


def _sanitize_match_lines(match: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = dict(match)
    sanitized["match_text"] = truncate_grep_line(sanitized.get("match_text"))
    raw_ctx = [item for item in (match.get("context") or []) if isinstance(item, dict)]
    numbers = _context_line_numbers(match, raw_ctx)
    sanitized["context"] = [
        {"line": line_no, "text": truncate_grep_line(item.get("text"))}
        for line_no, item in zip(numbers, raw_ctx)
    ]
    return sanitized


async def handle_grep_code(
    pattern: Annotated[str, Field(description="Exact literal string or regular expression to match across source files (Python, TypeScript/JS/TSX, C#, COBOL, Go, Rust, Java, C/C++, Markdown, configs).")],
    repo: Annotated[Optional[str], Field(description="Optional repository name or 'local_storage' to scope search. Omit to scan all indexed sources.")] = None,
    path_glob: Annotated[Optional[str], Field(description="Optional path filter. With wildcards it is an fnmatch glob ('*.cs', 'app/services/*'); without wildcards it is a file or folder ('Services_V2', 'src/app/main.py').")] = None,
    is_regex: Annotated[bool, Field(description="Set True to evaluate pattern as a Python regular expression; False (default) matches literal text. If a literal search finds nothing and the pattern looks like a regex (for example 'A|B'), the search runs again as a regex and pattern_mode says so.")] = False,
    case_sensitive: Annotated[bool, Field(description="Set True for case-sensitive matching; False (default) ignores case.")] = False,
    context_lines: Annotated[int, Field(description="Surrounding context lines per match, clamped to 0..10 (default 2). Lines > 400 chars are truncated.")] = 2,
    limit: Annotated[int, Field(description="Maximum matched lines per page, clamped to 1..100 (default 30).")] = 30,
    offset: Annotated[int, Field(description="0-based match offset for pagination (default 0). Advance by next_offset when has_more is True.")] = 0,
    path: Annotated[Optional[str], Field(description="Alias for path_glob (a file, folder, or glob). path_glob wins when both are given.")] = None,
) -> str:
    """Deterministic literal and regex pattern search across indexed repositories with bounded line lengths and pagination."""
    try:
        enforce_tool_permission(Role.VIEWER)
        reader_fn = _resolve_reader_factory()
        reader = reader_fn()

        safe_limit = max(1, min(int(limit if limit is not None else 30), 100))
        safe_offset = max(0, int(offset if offset is not None else 0))
        safe_context = max(0, min(int(context_lines if context_lines is not None else 2), 10))
        needed = safe_offset + safe_limit + 1
        path_filter = path_glob or path

        def _search(as_regex: bool) -> List[Dict[str, Any]]:
            if needed <= 100:
                raw_result = reader.grep_code(
                    pattern=pattern,
                    repo=repo,
                    path_glob=path_filter,
                    is_regex=as_regex,
                    case_sensitive=case_sensitive,
                    context_lines=safe_context,
                    limit=100,
                )
                return raw_result.get("matches", [])
            raw_result = execute_code_grep(
                pattern=pattern,
                storage_root=reader.storage_root,
                indexed_paths=reader._get_authorized_indexed_paths(),
                persistent_repos=reader._get_authorized_persistent_repos(),
                is_binary_fn=reader.is_binary_file,
                db_conn_factory=lambda: get_db_connection(),
                repo=repo,
                path_glob=path_filter,
                is_regex=as_regex,
                case_sensitive=case_sensitive,
                context_lines=safe_context,
                limit=needed,
                max_limit=needed,
            )
            return raw_result.get("matches", [])

        pattern_mode = "regex" if is_regex else "literal"
        all_matches = _search(is_regex)
        if not all_matches and not is_regex and looks_like_regex(pattern):
            all_matches = _search(True)
            pattern_mode = "regex (the literal text had no matches, so the pattern ran as a regex)"

        has_more = len(all_matches) > (safe_offset + safe_limit)
        page_slice = all_matches[safe_offset : safe_offset + safe_limit]
        sanitized_matches = [_sanitize_match_lines(m) for m in page_slice]
        next_offset = (safe_offset + safe_limit) if has_more else None

        payload = {
            "pattern": pattern,
            "pattern_mode": pattern_mode,
            "path_filter": path_filter,
            "total_matches": len(all_matches),
            "offset": safe_offset,
            "limit": safe_limit,
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
