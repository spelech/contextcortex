import logging
import sys
from typing import Optional, Annotated
from pydantic import Field

from app.services.auth import enforce_tool_permission, Role, ForbiddenError
from app.services.file_reader import get_file_reader_service, FileReaderService
from app.services.summarizer import get_summarizer_service, SummarizerService

logger = logging.getLogger("contextcortex.mcp.files")


def _get_tools_attr(name, default):
    t_mod = sys.modules.get("app.mcp.tools")
    return getattr(t_mod, name, default) if t_mod else default


async def handle_read_file(
    path: Annotated[str, Field(description="Relative or absolute file path within a watched local directory or uploaded local storage.")],
    repo: Annotated[Optional[str], Field(description="Optional repository identifier or storage namespace to target.")] = None,
    start_line: Annotated[Optional[int], Field(description="1-based starting line number (inclusive).")] = None,
    end_line: Annotated[Optional[int], Field(description="1-based ending line number (inclusive).")] = None
) -> str:
    """Read entire file content or bounded line ranges from monitored local directories or local storage with safety limits."""
    try:
        enforce_tool_permission(Role.VIEWER)
        reader_fn = _get_tools_attr("get_file_reader_service", get_file_reader_service)
        reader = reader_fn()

        result = reader.read_file(
            path=path,
            repo=repo,
            start_line=start_line,
            end_line=end_line
        )

        trunc_msg = f" (truncated at line limit)" if result.get("truncated") else ""
        header = (
            f"### File: `{result['filepath']}` ({result['size_bytes']} bytes, "
            f"lines {result['start_line']}-{result['end_line']} of {result['total_lines']}{trunc_msg})\n"
            f"- **Source:** `{result['source']}`\n\n"
        )
        return f"{header}```\n{result['content']}\n```"

    except ForbiddenError as fe:
        logger.warning(f"Forbidden error in handle_read_file ({path}): {fe}")
        return f"Forbidden: {str(fe)}"
    except FileNotFoundError as fne:
        return f"Error: File not found: {str(fne)}"
    except ValueError as ve:
        return f"Error: {str(ve)}"
    except Exception as e:
        logger.error(f"Error reading file '{path}': {e}")
        return f"Error reading file: {str(e)}"


async def handle_summarize_file(
    path: Annotated[str, Field(description="Path to the file to summarize (monitored local path or uploaded local storage).")],
    repo: Annotated[Optional[str], Field(description="Optional repository or storage namespace filter.")] = None,
    force_refresh: Annotated[bool, Field(description="If True, bypasses SQLite cache and regenerates a fresh LLM summary.")] = False
) -> str:
    """Retrieve an existing summary or generate a structured LLM executive summary for a large file."""
    try:
        enforce_tool_permission(Role.VIEWER)
        summarizer_fn = _get_tools_attr("get_summarizer_service", get_summarizer_service)
        summarizer = summarizer_fn()

        summary_text = summarizer.get_or_create_summary(
            filepath=path,
            repo=repo,
            force_refresh=force_refresh
        )

        if not summary_text or not summary_text.strip():
            return f"Notice: Could not generate summary for `{path}` (file may be empty or summarization failed)."

        return f"### Summary: `{path}`\n\n{summary_text.strip()}"

    except ForbiddenError as fe:
        logger.warning(f"Forbidden error in handle_summarize_file ({path}): {fe}")
        return f"Forbidden: {str(fe)}"
    except FileNotFoundError as fne:
        return f"Error: File not found: {str(fne)}"
    except ValueError as ve:
        return f"Error: {str(ve)}"
    except Exception as e:
        logger.error(f"Error summarizing file '{path}': {e}")
        return f"Error summarizing file: {str(e)}"
