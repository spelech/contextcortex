import logging
from typing import Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, Query, Depends
from fastapi.responses import JSONResponse

from app.services.file_reader import get_file_reader_service
from app.services.summarizer import get_summarizer_service
from app.services.auth import Role, ForbiddenError
from app.api.routers.auth import require_role

logger = logging.getLogger("contextcortex.api.files")
router = APIRouter()


class FileSummarizePayload(BaseModel):
    path: str = Field(..., description="Path to the file to summarize")
    repo: Optional[str] = Field(None, description="Optional repository or storage namespace")
    force_refresh: bool = Field(False, description="Whether to bypass cache and regenerate summary")


class GrepSearchPayload(BaseModel):
    pattern: str = Field(..., max_length=500, description="Substring pattern to search for")
    repo: Optional[str] = Field(None, description="Optional repository identifier or storage namespace")
    path_glob: Optional[str] = Field(None, description="Optional fnmatch file glob")
    is_regex: bool = Field(False, description="Whether pattern is a regex")
    case_sensitive: bool = Field(False, description="Whether matching is case-sensitive")
    context_lines: int = Field(2, ge=0, le=10, description="Surrounding context lines")
    limit: int = Field(30, ge=1, le=100, description="Maximum matches to return")


@router.get(
    "/admin/api/files/read",
    dependencies=[Depends(require_role(Role.VIEWER))],
)
async def api_read_file(
    path: str = Query(..., description="Target file path (relative to repo/storage or absolute within indexed root)"),
    repo: Optional[str] = Query(None, description="Optional repo or storage namespace"),
    start_line: Optional[int] = Query(None, description="1-based starting line number"),
    end_line: Optional[int] = Query(None, description="1-based ending line number"),
):
    try:
        raw_path = path.strip() if path else ""
        if not raw_path or "\x00" in raw_path or any(part == ".." for part in raw_path.replace("\\", "/").split("/")):
            return JSONResponse(status_code=400, content={"error": "Path traversal or invalid path detected."})
        raw_repo = repo.strip() if repo else None
        if raw_repo and ("\x00" in raw_repo or any(part == ".." for part in raw_repo.replace("\\", "/").split("/"))):
            return JSONResponse(status_code=400, content={"error": "Path traversal or invalid repo detected."})

        reader = get_file_reader_service()
        res = reader.read_file(
            path=raw_path,
            repo=raw_repo,
            start_line=start_line,
            end_line=end_line
        )
        return res
    except ForbiddenError as fe:
        logger.warning(f"Forbidden access reading file '{path}': {fe}")
        return JSONResponse(status_code=403, content={"error": "Access denied. Path is outside allowed repositories."})
    except IsADirectoryError:
        return JSONResponse(status_code=400, content={"error": f"Target path '{path}' is a directory, not a file."})
    except FileNotFoundError as fne:
        logger.warning(f"File not found reading '{path}': {fne}")
        return JSONResponse(status_code=404, content={"error": "File not found."})
    except ValueError as ve:
        logger.warning(f"Validation error reading file '{path}': {ve}")
        return JSONResponse(status_code=400, content={"error": "Invalid file parameters."})
    except Exception as e:
        logger.error(f"Error reading file '{path}': {e}")
        return JSONResponse(status_code=500, content={"error": "Internal server error reading file."})


@router.post(
    "/admin/api/files/summarize",
    dependencies=[Depends(require_role(Role.VIEWER))],
)
async def api_summarize_file(payload: FileSummarizePayload):
    try:
        raw_path = payload.path.strip() if payload.path else ""
        if not raw_path or "\x00" in raw_path or any(part == ".." for part in raw_path.replace("\\", "/").split("/")):
            return JSONResponse(status_code=400, content={"error": "Path traversal or invalid path detected."})
        raw_repo = payload.repo.strip() if payload.repo else None
        if raw_repo and ("\x00" in raw_repo or any(part == ".." for part in raw_repo.replace("\\", "/").split("/"))):
            return JSONResponse(status_code=400, content={"error": "Path traversal or invalid repo detected."})

        reader = get_file_reader_service()
        safe_path, _ = reader.resolve_safe_path(raw_path, repo=raw_repo)
        summarizer = get_summarizer_service()
        summary_text = summarizer.get_or_create_summary(
            filepath=safe_path,
            repo=payload.repo,
            force_refresh=payload.force_refresh
        )
        return {
            "path": payload.path,
            "repo": payload.repo,
            "summary": summary_text,
            "status": "success"
        }
    except ForbiddenError as fe:
        logger.warning(f"Forbidden access summarizing file '{payload.path}': {fe}")
        return JSONResponse(status_code=403, content={"error": "Access denied. Path is outside allowed repositories."})
    except FileNotFoundError as fne:
        logger.warning(f"File not found summarizing '{payload.path}': {fne}")
        return JSONResponse(status_code=404, content={"error": "File not found."})
    except ValueError as ve:
        logger.warning(f"Validation error summarizing file '{payload.path}': {ve}")
        return JSONResponse(status_code=400, content={"error": "Invalid file parameters."})
    except Exception as e:
        logger.error(f"Error summarizing file '{payload.path}': {e}")
        return JSONResponse(status_code=500, content={"error": "Internal server error summarizing file."})


@router.post(
    "/api/search/grep",
    dependencies=[Depends(require_role(Role.VIEWER))],
)
@router.post(
    "/admin/api/search/grep",
    dependencies=[Depends(require_role(Role.VIEWER))],
)
async def api_grep_code(payload: GrepSearchPayload):
    try:
        import re
        raw_pattern = payload.pattern.strip() if payload.pattern else ""
        if not raw_pattern:
            return JSONResponse(status_code=400, content={"error": "pattern must be a non-empty string."})

        raw_repo = payload.repo.strip() if payload.repo else None
        if raw_repo and ("\x00" in raw_repo or any(part == ".." for part in raw_repo.replace("\\", "/").split("/"))):
            return JSONResponse(status_code=400, content={"error": "Path traversal or invalid repo detected."})

        safe_pattern = re.escape(raw_pattern)
        reader = get_file_reader_service()
        result = reader.grep_code(
            pattern=safe_pattern,
            repo=raw_repo,
            path_glob=payload.path_glob,
            is_regex=True,
            case_sensitive=payload.case_sensitive,
            context_lines=payload.context_lines,
            limit=payload.limit,
        )
        result["pattern"] = raw_pattern
        return result
    except ForbiddenError as fe:
        logger.warning(f"Forbidden access during grep_code: {fe}")
        return JSONResponse(status_code=403, content={"error": "Access denied."})
    except ValueError as ve:
        logger.warning(f"Validation error during grep_code: {ve}")
        return JSONResponse(status_code=400, content={"error": "Invalid search parameters."})
    except Exception as e:
        logger.error(f"Error in api_grep_code: {e}")
        return JSONResponse(status_code=500, content={"error": "Internal server error during grep search."})
