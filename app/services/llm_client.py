import os
import json
import logging
from typing import Dict

logger = logging.getLogger("contextcortex.llm_client")


def get_llm_extra_headers() -> Dict[str, str]:
    """
    Returns extra HTTP headers for OpenAI-compatible gateway requests, parsed from the
    LLM_EXTRA_HEADERS environment variable (a JSON object of header name -> value).
    Returns an empty dict when unset or invalid.
    """
    raw = os.getenv("LLM_EXTRA_HEADERS", "").strip()
    if not raw:
        return {}

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning(f"Ignoring LLM_EXTRA_HEADERS: invalid JSON ({e})")
        return {}

    if not isinstance(parsed, dict):
        logger.warning("Ignoring LLM_EXTRA_HEADERS: value must be a JSON object")
        return {}

    headers: Dict[str, str] = {}
    for k, v in parsed.items():
        if v is None:
            continue
        name = str(k).strip()
        val = str(v)
        if not name:
            continue
        if "\r" in name or "\n" in name or "\r" in val or "\n" in val:
            logger.warning(f"Ignoring header '{name}' in LLM_EXTRA_HEADERS: CR/LF characters are not permitted")
            continue
        headers[name] = val
    return headers
