"""Shared OpenAI-compatible chat client helpers with per-model parameter compatibility memory (#222)."""

import json
import logging
import os
import threading
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("contextcortex.llm_client")

_CAPABILITY_LOCK = threading.Lock()
_MODEL_CAPABILITIES: Dict[str, Set[str]] = {}


def reset_model_capabilities() -> None:
    """Clears remembered per-model chat parameter overrides (used in tests)."""
    with _CAPABILITY_LOCK:
        _MODEL_CAPABILITIES.clear()


def _model_flags(model: str) -> Set[str]:
    key = (model or "").strip().lower()
    with _CAPABILITY_LOCK:
        return set(_MODEL_CAPABILITIES.get(key, ()))


def _remember_flag(model: str, flag: str) -> None:
    key = (model or "").strip().lower()
    if not key:
        return
    with _CAPABILITY_LOCK:
        _MODEL_CAPABILITIES.setdefault(key, set()).add(flag)


def _is_bad_request(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    if status == 400:
        return True
    low = str(exc).lower()
    return any(tok in low for tok in ("400", "unsupported", "not support", "invalid", "unexpected keyword"))


def _classify_param_rejection(exc: Exception, sent_kwargs: Dict[str, Any]) -> List[str]:
    """Returns capability flags to enable when a 400 error rejects temperature or max_tokens."""
    if not _is_bad_request(exc):
        return []
    low = str(exc).lower()
    flags: List[str] = []
    if "temperature" in sent_kwargs and "temperature" in low:
        flags.append("no_temperature")
    if "max_tokens" in sent_kwargs and ("max_tokens" in low or "max_completion_tokens" in low):
        flags.append("use_max_completion_tokens")
    return flags


def create_chat_completion(
    client: Any,
    *,
    model: str,
    messages: List[Dict[str, Any]],
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    **extra: Any,
) -> Any:
    """Calls `client.chat.completions.create`, omitting `temperature` by default and auto-retrying 400 param errors.

    Remembers per-model rejections (`temperature`, `max_tokens` -> `max_completion_tokens`) so subsequent calls
    avoid failing round-trips on reasoning models.
    """
    flags = _model_flags(model)
    for _attempt in range(3):
        kwargs: Dict[str, Any] = {"model": model, "messages": messages, **extra}
        if temperature is not None and "no_temperature" not in flags:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            if "use_max_completion_tokens" in flags:
                kwargs["max_completion_tokens"] = max_tokens
            else:
                kwargs["max_tokens"] = max_tokens
        try:
            return client.chat.completions.create(**kwargs)
        except Exception as exc:
            new_flags = [f for f in _classify_param_rejection(exc, kwargs) if f not in flags]
            if not new_flags:
                raise
            for flag in new_flags:
                flags.add(flag)
                _remember_flag(model, flag)
            logger.info(
                f"Model '{model}' rejected chat parameter(s) ({', '.join(new_flags)}); retrying with compatible args."
            )
    return client.chat.completions.create(model=model, messages=messages, **extra)


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


__all__ = [
    "create_chat_completion",
    "get_llm_extra_headers",
    "reset_model_capabilities",
]
