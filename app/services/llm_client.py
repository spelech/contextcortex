"""Shared OpenAI-compatible chat client helpers with parameter compatibility memory, transient retry, and per-model stats (#222, #228)."""

import json
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("contextcortex.llm_client")

_CAPABILITY_LOCK = threading.Lock()
_MODEL_CAPABILITIES: Dict[str, Set[str]] = {}
_MODEL_STATS: Dict[str, Dict[str, Any]] = {}

_TRANSIENT_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})
_TRANSIENT_MARKERS = (
    "429", "500", "502", "503", "504", "timeout", "timed out", "rate limit",
    "temporarily unavailable", "service unavailable", "connection error", "connection reset",
)


def reset_model_capabilities() -> None:
    """Clears remembered per-model chat parameter overrides and call/failure counters (used in tests)."""
    with _CAPABILITY_LOCK:
        _MODEL_CAPABILITIES.clear()
        _MODEL_STATS.clear()


def get_llm_call_stats() -> Dict[str, Dict[str, Any]]:
    """Returns per-model chat completion call, retry, and failure counters for /admin/api/stats (#228)."""
    with _CAPABILITY_LOCK:
        return {model: dict(stats) for model, stats in _MODEL_STATS.items()}


def _record_call_stat(model: str, *, calls: int = 0, retries: int = 0, failures: int = 0, error: Optional[str] = None) -> Dict[str, Any]:
    key = (model or "unknown").strip() or "unknown"
    with _CAPABILITY_LOCK:
        entry = _MODEL_STATS.setdefault(key, {"calls": 0, "retries": 0, "failures": 0, "last_error": None})
        entry["calls"] += calls
        entry["retries"] += retries
        entry["failures"] += failures
        if error is not None:
            entry["last_error"] = " ".join(error.split())[:160]
        return dict(entry)


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
    if getattr(exc, "status_code", None) == 400:
        return True
    low = str(exc).lower()
    return any(tok in low for tok in ("400", "unsupported", "not support", "invalid", "unexpected keyword"))


def _is_transient_error(exc: Exception) -> bool:
    if getattr(exc, "status_code", None) in _TRANSIENT_STATUS_CODES:
        return True
    low = f"{type(exc).__name__} {exc}".lower()
    return any(tok in low for tok in _TRANSIENT_MARKERS)


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
    transient_retries: int = 1,
    retry_backoff: float = 0.5,
    **extra: Any,
) -> Any:
    """Calls `client.chat.completions.create`, omitting `temperature` by default, auto-retrying 400 param errors and transient 429/5xx/timeouts."""
    _record_call_stat(model, calls=1)
    flags = _model_flags(model)
    transient_left = max(0, int(transient_retries))
    param_attempts = 0
    while True:
        kwargs: Dict[str, Any] = {"model": model, "messages": messages, **extra}
        if temperature is not None and "no_temperature" not in flags:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_completion_tokens" if "use_max_completion_tokens" in flags else "max_tokens"] = max_tokens
        try:
            return client.chat.completions.create(**kwargs)
        except Exception as exc:
            new_flags = [f for f in _classify_param_rejection(exc, kwargs) if f not in flags]
            if new_flags and param_attempts < 2:
                param_attempts += 1
                for flag in new_flags:
                    flags.add(flag)
                    _remember_flag(model, flag)
                _record_call_stat(model, retries=1)
                logger.info(
                    f"Model '{model}' rejected chat parameter(s) ({', '.join(new_flags)}); retrying with compatible args."
                )
                continue
            if transient_left > 0 and _is_transient_error(exc):
                transient_left -= 1
                _record_call_stat(model, retries=1)
                logger.info(f"Transient chat completion error for '{model}' ({exc}); retrying after {retry_backoff:.2f}s.")
                if retry_backoff > 0:
                    time.sleep(retry_backoff)
                continue
            _record_call_stat(model, failures=1, error=str(exc))
            raise


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
    "get_llm_call_stats",
    "get_llm_extra_headers",
    "reset_model_capabilities",
]
