import logging
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
