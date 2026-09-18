import logging
from typing import Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.services.file_reader import get_file_reader_service
from app.services.summarizer import get_summarizer_service
from app.services.auth import ForbiddenError

logger = logging.getLogger("contextcortex.api.files")
router = APIRouter()


class FileSummarizePayload(BaseModel):
    path: str = Field(..., description="Path to the file to summarize")
    repo: Optional[str] = Field(None, description="Optional repository or storage namespace")
    force_refresh: bool = Field(False, description="Whether to bypass cache and regenerate summary")


@router.get("/admin/api/files/read")
async def api_read_file(
    path: str = Query(..., description="Target file path (relative to repo/storage or absolute within indexed root)"),
    repo: Optional[str] = Query(None, description="Optional repo or storage namespace"),
    start_line: Optional[int] = Query(None, description="1-based starting line number"),
    end_line: Optional[int] = Query(None, description="1-based ending line number"),
):
    try:
        reader = get_file_reader_service()
        res = reader.read_file(
            path=path,
            repo=repo,
            start_line=start_line,
            end_line=end_line
        )
        return res
    except ForbiddenError as fe:
        return JSONResponse(status_code=403, content={"error": str(fe)})
    except FileNotFoundError as fne:
        return JSONResponse(status_code=404, content={"error": str(fne)})
    except ValueError as ve:
        return JSONResponse(status_code=400, content={"error": str(ve)})
    except Exception as e:
        logger.error(f"Error reading file '{path}': {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.post("/admin/api/files/summarize")
async def api_summarize_file(payload: FileSummarizePayload):
    try:
        summarizer = get_summarizer_service()
        summary_text = summarizer.get_or_create_summary(
            filepath=payload.path,
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
        return JSONResponse(status_code=403, content={"error": str(fe)})
    except FileNotFoundError as fne:
        return JSONResponse(status_code=404, content={"error": str(fne)})
    except ValueError as ve:
        return JSONResponse(status_code=400, content={"error": str(ve)})
    except Exception as e:
        logger.error(f"Error summarizing file '{payload.path}': {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})
