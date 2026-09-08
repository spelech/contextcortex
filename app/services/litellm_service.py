import os
import logging
from typing import Optional, Dict, Any, List
import httpx

from app.services.database import get_embedding_db_config

logger = logging.getLogger("contextcortex.litellm")


async def discover_models(
    url: Optional[str] = None,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Queries LiteLLM GET /v1/models endpoint, categorizes returned models by capability
    (embedding, vision OCR, chat completion), and returns structured model metadata.
    """
    db_cfg: Dict[str, Any] = {}
    try:
        db_cfg = get_embedding_db_config()
    except Exception as e:
        logger.debug(f"Failed to fetch db config for litellm discovery: {e}")

    # Resolve URL: explicitly passed -> SQLite db config -> environment -> fallback
    raw_url = (
        (url.strip() if url and url.strip() else None)
        or (db_cfg.get("litellm_url") if db_cfg and db_cfg.get("litellm_url") else None)
        or os.getenv("LITELLM_URL")
        or "http://litellm:4000/v1"
    )

    # Resolve API Key: explicitly passed -> SQLite db config -> environment -> fallback
    resolved_api_key = (
        (api_key.strip() if api_key and api_key.strip() else None)
        or (db_cfg.get("litellm_api_key") if db_cfg and db_cfg.get("litellm_api_key") else None)
        or os.getenv("LITELLM_API_KEY")
        or "dummy"
    )

    # Normalize URL to target /models endpoint
    clean_url = raw_url.strip().rstrip("/")
    if clean_url.endswith("/models"):
        endpoint = clean_url
    else:
        if not clean_url.endswith("/v1"):
            clean_url = f"{clean_url}/v1"
        endpoint = f"{clean_url}/models"

    headers = {"Authorization": f"Bearer {resolved_api_key}"}

    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            response = await client.get(endpoint, headers=headers)

        if response.status_code != 200:
            error_msg = f"LiteLLM returned status {response.status_code}: {response.text.strip() or response.reason_phrase}"
            logger.warning(f"LiteLLM model discovery failed: {error_msg}")
            return {
                "status": "error",
                "message": error_msg,
                "total_models": 0,
                "models": [],
                "embedding_models": [],
                "vision_models": [],
                "chat_models": [],
            }

        payload = response.json()
        raw_items: List[Any] = []
        if isinstance(payload, dict):
            if "data" in payload and isinstance(payload["data"], list):
                raw_items = payload["data"]
            elif "models" in payload and isinstance(payload["models"], list):
                raw_items = payload["models"]
        elif isinstance(payload, list):
            raw_items = payload

        models: List[Dict[str, Any]] = []
        embedding_models: List[str] = []
        vision_models: List[str] = []
        chat_models: List[str] = []

        vision_patterns = ["vision", "-vl", "flash", "pro", "gemini", "gpt-4", "claude", "qwen3-vl"]
        embedding_patterns = ["embed", "bge", "text-embedding"]
        image_gen_patterns = ["dall-e", "midjourney", "stable-diffusion", "flux"]

        for item in raw_items:
            if isinstance(item, dict):
                model_id = str(item.get("id") or item.get("model") or item.get("name") or "").strip()
                mode = str(item.get("mode") or "").strip()
                normalized_model = dict(item)
            elif isinstance(item, str):
                model_id = item.strip()
                mode = ""
                normalized_model = {"id": model_id, "mode": mode}
            else:
                continue

            if not model_id:
                continue

            models.append(normalized_model)
            mid_lower = model_id.lower()
            mode_lower = mode.lower()

            # Classification
            is_embedding = (mode_lower == "embedding") or any(pat in mid_lower for pat in embedding_patterns)
            is_image_gen = (mode_lower in ["image_generation", "image-generation", "dall-e"]) or any(
                pat in mid_lower for pat in image_gen_patterns
            )

            if is_embedding:
                embedding_models.append(model_id)

            if not is_embedding and not is_image_gen:
                # Vision / Multimodal model categorization
                if mode_lower in ["vision", "multimodal"] or any(pat in mid_lower for pat in vision_patterns):
                    vision_models.append(model_id)

                # Chat model categorization
                if mode_lower == "chat" or mode_lower not in ["embedding", "image_generation"]:
                    chat_models.append(model_id)

        embedding_models = sorted(list(set(embedding_models)))
        vision_models = sorted(list(set(vision_models)))
        chat_models = sorted(list(set(chat_models)))
        models.sort(key=lambda m: str(m.get("id", "")))

        return {
            "status": "success",
            "total_models": len(models),
            "models": models,
            "embedding_models": embedding_models,
            "vision_models": vision_models,
            "chat_models": chat_models,
        }

    except (httpx.TimeoutException, TimeoutError) as e:
        logger.warning(f"LiteLLM model discovery timed out: {e}")
        return {
            "status": "error",
            "message": f"LiteLLM request timed out: {e}",
            "total_models": 0,
            "models": [],
            "embedding_models": [],
            "vision_models": [],
            "chat_models": [],
        }
    except httpx.ConnectError as e:
        logger.warning(f"LiteLLM connection error: {e}")
        return {
            "status": "error",
            "message": f"LiteLLM connection failed: {e}",
            "total_models": 0,
            "models": [],
            "embedding_models": [],
            "vision_models": [],
            "chat_models": [],
        }
    except httpx.HTTPStatusError as e:
        logger.warning(f"LiteLLM HTTP error: {e}")
        return {
            "status": "error",
            "message": f"LiteLLM returned HTTP status {e.response.status_code}: {e}",
            "total_models": 0,
            "models": [],
            "embedding_models": [],
            "vision_models": [],
            "chat_models": [],
        }
    except Exception as e:
        logger.exception(f"Unexpected error discovering LiteLLM models: {e}")
        return {
            "status": "error",
            "message": f"Failed to discover models: {e}",
            "total_models": 0,
            "models": [],
            "embedding_models": [],
            "vision_models": [],
            "chat_models": [],
        }
