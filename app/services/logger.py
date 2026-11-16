import logging
import os
import sys
import threading
from collections import deque
from datetime import datetime
from typing import List, Dict, Any, Optional

class RingBufferHandler(logging.Handler):
    """Thread-safe ring buffer log handler retaining recent events for admin diagnostics."""
    def __init__(self, capacity: int = 500):
        super().__init__()
        self.capacity = capacity
        self.buffer = deque(maxlen=capacity)
        self._buf_lock = threading.Lock()

    def emit(self, record: logging.LogRecord):
        try:
            log_entry = {
                "timestamp": datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S"),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
                "traceback": None
            }
            if record.exc_info:
                import traceback
                log_entry["traceback"] = "".join(traceback.format_exception(*record.exc_info))
            with self._buf_lock:
                self.buffer.append(log_entry)
        except Exception:
            self.handleError(record)

_diagnostic_handler = RingBufferHandler(capacity=500)
_diagnostic_handler.setLevel(logging.INFO)
logging.getLogger().addHandler(_diagnostic_handler)

def get_diagnostic_logs(limit: int = 200, level: Optional[str] = None, search: Optional[str] = None) -> List[Dict[str, Any]]:
    with _diagnostic_handler._buf_lock:
        logs = list(_diagnostic_handler.buffer)
    if level and level.upper() != "ALL":
        logs = [l for l in logs if l["level"] == level.upper()]
    if search and search.strip():
        q = search.lower().strip()
        logs = [l for l in logs if q in l["message"].lower() or q in l["logger"].lower()]
    return list(reversed(logs[-limit:]))

def clear_diagnostic_logs():
    with _diagnostic_handler._buf_lock:
        _diagnostic_handler.buffer.clear()


APP_LOGGER_NAME = "contextcortex"
CONSOLE_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_CONSOLE_MARKER = "_contextcortex_console"


def resolve_log_level(value: Optional[str] = None) -> int:
    """Returns the numeric level for LOG_LEVEL (name or number). Unknown values give INFO."""
    raw = (value if value is not None else os.getenv("LOG_LEVEL", "")).strip().upper()
    if raw.isdigit():
        return int(raw)
    level = logging.getLevelName(raw) if raw else logging.INFO
    return level if isinstance(level, int) else logging.INFO


def configure_application_logging(level: Optional[str] = None) -> logging.Handler:
    """
    Sends the 'contextcortex.*' loggers to stdout and to the diagnostic ring buffer.

    logging.basicConfig() cannot do this: this module adds the ring buffer to the
    root logger at import time, so basicConfig() sees a handler and does nothing.
    The root level stays WARNING, so third-party INFO lines (httpx etc.) stay hidden.
    Safe to call more than once: it never adds a second console handler.
    """
    numeric_level = resolve_log_level(level)
    root = logging.getLogger()
    if _diagnostic_handler not in root.handlers:
        root.addHandler(_diagnostic_handler)
    console = next((h for h in root.handlers if getattr(h, _CONSOLE_MARKER, False)), None)
    if console is None:
        console = logging.StreamHandler(sys.stdout)
        setattr(console, _CONSOLE_MARKER, True)
        console.setFormatter(logging.Formatter(CONSOLE_FORMAT))
        root.addHandler(console)
    if numeric_level > logging.WARNING:
        root.setLevel(numeric_level)
    logging.getLogger(APP_LOGGER_NAME).setLevel(numeric_level)
    return console
