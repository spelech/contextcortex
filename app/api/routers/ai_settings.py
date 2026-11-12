import logging
from typing import Optional
from urllib.parse import urlsplit
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from app.services.auth import Role
from app.api.routers.auth import require_role
from app.models.schemas import (
    EmbeddingSettingsRequest,
    FileSettingsRequest,
    AIGatewaySettingsRequest,
)
import app.services.database as db_service
import app.services.embeddings as emb_service
import app.services.litellm_service as litellm_service

logger = logging.getLogger("contextcortex.api")

router = APIRouter()


@router.get(
    "/admin/api/models/discover",
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def api_discover_models(url: Optional[str] = None, api_key: Optional[str] = None):
    try:
        if url:
            parsed = urlsplit(url.strip())
            if parsed.scheme not in ("http", "https"):
                return JSONResponse(
                    status_code=400,
                    content={"status": "error", "error": "Invalid URL scheme: only http and https are allowed."},
                )
            host = (parsed.hostname or "").lower()
            if not host or host in ("169.254.169.254", "metadata.google.internal") or host.startswith("169.254."):
                return JSONResponse(
                    status_code=400,
                    content={"status": "error", "error": "Invalid or restricted target host."},
                )
        return await litellm_service.discover_models(url=url, api_key=api_key)
    except Exception as e:
        logger.error(f"Error discovering models: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "error": "Failed to discover models."})


@router.get(
    "/admin/api/settings/ai-gateway",
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def api_get_ai_gateway_settings():
    try:
        return db_service.get_ai_gateway_config()
    except Exception as e:
        logger.error(f"Error reading AI gateway settings: {e}")
        return JSONResponse(status_code=500, content={"error": "Failed to read AI gateway settings."})


@router.post(
    "/admin/api/settings/ai-gateway",
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def api_save_ai_gateway_settings(payload: AIGatewaySettingsRequest):
    try:
        updated = db_service.set_ai_gateway_config(
            url=payload.url,
            api_key=payload.api_key,
            chat_model=payload.chat_model,
            vision_ocr_model=payload.vision_ocr_model,
            embedding_model=payload.embedding_model,
        )
        try:
            emb_service.init_embeddings()
        except Exception as init_err:
            logger.debug(f"Embedding hot-reload after AI gateway update skipped: {init_err}")
        return {
            "status": "success",
            "message": "AI & Model Gateway settings saved successfully.",
            "config": updated,
        }
    except Exception as e:
        logger.error(f"Error saving AI gateway settings: {e}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "error": "Failed to save AI gateway settings."},
        )


@router.get(
    "/admin/api/settings/embedding",
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def api_get_embedding_settings():
    try:
        return emb_service.get_embedding_config()
    except Exception as e:
        logger.error(f"Error reading embedding settings: {e}")
        return JSONResponse(status_code=500, content={"error": "Failed to read embedding settings."})


@router.post(
    "/admin/api/settings/embedding",
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def api_save_embedding_settings(payload: EmbeddingSettingsRequest):
    try:
        do_rebuild = bool(payload.rebuild_index or payload.rebuild)
        updated_cfg = emb_service.update_embedding_config(
            provider=payload.provider,
            dense_model=payload.dense_model,
            sparse_model=payload.sparse_model,
            threads=payload.threads,
            batch_size=payload.batch_size,
            litellm_url=payload.litellm_url,
            litellm_api_key=payload.litellm_api_key,
            vision_ocr_model=payload.vision_ocr_model,
            chat_model=payload.chat_model,
            allow_fallback=payload.allow_fallback,
            fallback_dense_model=payload.fallback_dense_model,
            rebuild_index=do_rebuild,
        )
        return {
            "status": "success",
            "message": "Embedding engine settings updated successfully.",
            "config": updated_cfg,
        }
    except ValueError as ve:
        err_str = str(ve)
        logger.warning(f"Rejected embedding settings update: {err_str}")
        safe_msg = (
            "Explicit rebuild confirmation is required when changing embedding model dimensions."
            if "rebuild confirmation" in err_str.lower()
            else "Invalid embedding settings provided."
        )
        return JSONResponse(
            status_code=400,
            content={"status": "error", "error": safe_msg, "message": safe_msg},
        )
    except Exception as e:
        logger.error(f"Error updating embedding settings: {e}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "error": "Failed to update embedding settings.", "message": "Failed to update embedding settings."},
        )


@router.get(
    "/admin/api/settings/files",
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def api_get_file_settings():
    try:
        return db_service.get_file_settings()
    except Exception as e:
        logger.error(f"Error reading file settings: {e}")
        return JSONResponse(status_code=500, content={"error": "Failed to read file settings."})


@router.post(
    "/admin/api/settings/files",
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def api_save_file_settings(payload: FileSettingsRequest):
    try:
        data = payload.model_dump(exclude_unset=True)
        return db_service.set_file_settings(data)
    except Exception as e:
        logger.error(f"Error saving file settings: {e}")
        return JSONResponse(status_code=500, content={"error": "Failed to save file settings."})
