import json
import logging
import sys
from typing import Optional, Annotated
from pydantic import Field

from app.services.auth import enforce_tool_permission, Role, ForbiddenError
from app.services.file_reader import get_file_reader_service, FileReaderService
from app.services.summarizer import get_summarizer_service, SummarizerService
from app.mcp.handlers.grep_handlers import handle_grep_code

logger = logging.getLogger("contextcortex.mcp.files")


def _get_tools_attr(name, default):
    t_mod = sys.modules.get("app.mcp.tools")
    return getattr(t_mod, name, default) if t_mod else default


def _strip_repo_prefix(filepath: Optional[str]) -> str:
    if not filepath:
        return ""
    res = filepath.split("://", 1)[1] if "://" in filepath else filepath
    return res.replace("\\", "/")


async def handle_read_file(
    path: Annotated[str, Field(description="Relative or absolute file path within an indexed repository, watched directory, or local storage (supports Python, TypeScript/JS/TSX, C#, COBOL, Go, Rust, Java, C/C++, Markdown, and config files).")],
    repo: Annotated[Optional[str], Field(description="Optional repository name or 'local_storage' namespace. Recommended when reading relative paths or reconstructing ephemeral Git files from vector chunks.")] = None,
    start_line: Annotated[Optional[int], Field(description="1-based inclusive starting line number (default 1). Pass next_start_line from a prior call to paginate long files.")] = None,
    end_line: Annotated[Optional[int], Field(description="1-based inclusive ending line number (default end of file, bounded by read_file_max_lines=2000 per call).")] = None,
) -> str:
    """Read bounded 1-based line ranges or full file content from disk, shallow clones, or vector chunk reconstruction."""
    try:
        enforce_tool_permission(Role.VIEWER)
        reader_fn = _get_tools_attr("get_file_reader_service", get_file_reader_service)
        reader = reader_fn()

        result = reader.read_file(
            path=path,
            repo=repo,
            start_line=start_line,
            end_line=end_line,
        )

        s_line = result.get("start_line")
        e_line = result.get("end_line")
        t_lines = result.get("total_lines")
        is_truncated = bool(result.get("truncated", False))
        has_more = bool(
            t_lines is not None
            and e_line is not None
            and t_lines > 0
            and e_line < t_lines
        )
        next_start_line = (e_line + 1) if (has_more and e_line is not None) else None

        return json.dumps({
            "file": _strip_repo_prefix(result.get("filepath") or path),
            "repo": repo,
            "source": result.get("source"),
            "lines": [s_line, e_line],
            "start_line": s_line,
            "end_line": e_line,
            "total_lines": t_lines,
            "has_more": has_more,
            "next_start_line": next_start_line,
            "size_bytes": result.get("size_bytes"),
            "truncated": is_truncated,
            "content": result.get("content", ""),
        })

    except ForbiddenError as fe:
        logger.warning(f"Forbidden error in handle_read_file ({path}): {fe}")
        return json.dumps({"error": f"Forbidden: {str(fe)}", "forbidden": True})
    except FileNotFoundError as fne:
        return json.dumps({"error": f"File not found: {str(fne)}"})
    except ValueError as ve:
        return json.dumps({"error": str(ve)})
    except Exception as e:
        logger.error(f"Error reading file '{path}': {e}")
        return json.dumps({"error": f"Error reading file: {str(e)}"})


async def handle_summarize_file(
    path: Annotated[str, Field(description="Relative or absolute path to the source or documentation file to summarize (Python, TypeScript/JS/TSX, C#, COBOL, Go, Rust, Java, C/C++, Markdown, PDF).")],
    repo: Annotated[Optional[str], Field(description="Optional repository identifier or 'local_storage' namespace filter.")] = None,
    force_refresh: Annotated[bool, Field(description="Set True to bypass cached summaries in relational storage and generate a fresh LLM executive summary (default False).")] = False,
) -> str:
    """Retrieve a cached file summary or generate a structured LLM executive summary for large source or documentation files."""
    try:
        enforce_tool_permission(Role.VIEWER)
        summarizer_fn = _get_tools_attr("get_summarizer_service", get_summarizer_service)
        summarizer = summarizer_fn()

        summary_text = summarizer.get_or_create_summary(
            filepath=path,
            repo=repo,
            force_refresh=force_refresh,
        )

        if not summary_text or not summary_text.strip():
            return json.dumps({
                "file": _strip_repo_prefix(path),
                "repo": repo,
                "summary": None,
                "error": f"Could not generate summary for '{path}' (file may be empty or summarization failed).",
            })

        return json.dumps({
            "file": _strip_repo_prefix(path),
            "repo": repo,
            "summary": summary_text.strip(),
        })

    except ForbiddenError as fe:
        logger.warning(f"Forbidden error in handle_summarize_file ({path}): {fe}")
        return json.dumps({"error": f"Forbidden: {str(fe)}", "forbidden": True})
    except FileNotFoundError as fne:
        return json.dumps({"error": f"File not found: {str(fne)}"})
    except ValueError as ve:
        return json.dumps({"error": str(ve)})
    except Exception as e:
        logger.error(f"Error summarizing file '{path}': {e}")
        return json.dumps({"error": f"Error summarizing file: {str(e)}"})


__all__ = [
    "handle_read_file",
    "handle_summarize_file",
    "handle_grep_code",
]
