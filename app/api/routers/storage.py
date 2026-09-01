import os
import logging
from typing import Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, Request, UploadFile, File, Form, Query
from fastapi.responses import JSONResponse

from app.services.local_storage import get_local_storage_service
from app.services.auth import Role, enforce_tool_permission

logger = logging.getLogger("contextcortex.api.storage")
router = APIRouter()

class FileUploadPayload(BaseModel):
    path: str = Field(..., description="Target relative file path")
    content: str = Field(..., description="File text content")
    repo: Optional[str] = "local_storage"
    category: Optional[str] = None

@router.post("/admin/api/storage/upload")
async def api_upload_storage_file(request: Request):
    try:
        storage = get_local_storage_service()
        content_type = request.headers.get("content-type", "")

        if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
            form = await request.form()
            file = form.get("file")
            path = form.get("path")
            repo = form.get("repo") or "local_storage"
            category = form.get("category")
            if file and hasattr(file, "read"):
                rel_path = path or getattr(file, "filename", "uploaded_file")
                content_bytes = await file.read()
                res = storage.save_file(rel_path, content_bytes, repo=repo, category=category)
                return res
            elif path and form.get("content") is not None:
                content = form.get("content")
                res = storage.save_file(path, content, repo=repo, category=category)
                return res
            else:
                return JSONResponse(status_code=400, content={"error": "Missing file upload or content in form"})

        # JSON payload handling
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(status_code=400, content={"error": "Missing file upload or JSON payload"})

        if not isinstance(body, dict) or "path" not in body or "content" not in body:
            return JSONResponse(status_code=400, content={"error": "Missing path or content in JSON payload"})

        path = body["path"]
        content = body["content"]
        repo = body.get("repo") or "local_storage"
        category = body.get("category")

        res = storage.save_file(path, content, repo=repo, category=category)
        return res
    except ValueError as ve:
        return JSONResponse(status_code=400, content={"error": str(ve)})
    except Exception as e:
        logger.error(f"Error uploading storage file: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.put("/admin/api/storage/file")
async def api_replace_storage_file(payload: FileUploadPayload):
    try:
        storage = get_local_storage_service()
        res = storage.save_file(payload.path, payload.content, repo=payload.repo or "local_storage", category=payload.category)
        return res
    except ValueError as ve:
        return JSONResponse(status_code=400, content={"error": str(ve)})
    except Exception as e:
        logger.error(f"Error replacing storage file: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.get("/admin/api/storage/file")
async def api_get_storage_file(path: str = Query(..., description="Relative file path")):
    try:
        storage = get_local_storage_service()
        return storage.read_file_content(path)
    except FileNotFoundError:
        return JSONResponse(status_code=404, content={"error": f"File '{path}' not found"})
    except ValueError as ve:
        return JSONResponse(status_code=400, content={"error": str(ve)})
    except Exception as e:
        logger.error(f"Error reading storage file '{path}': {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.delete("/admin/api/storage/file")
async def api_delete_storage_file(path: str = Query(..., description="Relative file path")):
    try:
        storage = get_local_storage_service()
        res = storage.delete_file(path)
        return res
    except ValueError as ve:
        return JSONResponse(status_code=400, content={"error": str(ve)})
    except Exception as e:
        logger.error(f"Error deleting storage file '{path}': {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.get("/admin/api/storage/tree")
async def api_get_storage_tree(folder: Optional[str] = Query(None, description="Subfolder to inspect")):
    try:
        storage = get_local_storage_service()
        return storage.get_file_tree(folder)
    except ValueError as ve:
        return JSONResponse(status_code=400, content={"error": str(ve)})
    except Exception as e:
        logger.error(f"Error reading storage tree: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})
