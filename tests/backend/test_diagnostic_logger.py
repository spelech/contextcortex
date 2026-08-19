import pytest
import logging
from unittest.mock import MagicMock, patch
from app.services.logger import RingBufferHandler, get_diagnostic_logs, clear_diagnostic_logs
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.routes import router


def test_ring_buffer_logging():
    clear_diagnostic_logs()
    test_logger = logging.getLogger("contextcortex.test")
    test_logger.setLevel(logging.INFO)
    test_logger.info("Test info message")
    test_logger.warning("Test warning message")
    test_logger.error("Test error message")

    logs = get_diagnostic_logs(limit=10)
    assert len(logs) == 3
    messages = [l["message"] for l in logs]
    assert "Test info message" in messages
    assert "Test warning message" in messages
    assert "Test error message" in messages

    # Test filtering by level
    error_logs = get_diagnostic_logs(level="ERROR")
    assert len(error_logs) == 1
    assert all(l["level"] == "ERROR" for l in error_logs)

    # Test search filtering by message and logger
    search_msg_logs = get_diagnostic_logs(search="warning")
    assert len(search_msg_logs) == 1
    assert search_msg_logs[0]["message"] == "Test warning message"

    search_logger_logs = get_diagnostic_logs(search="contextcortex.test")
    assert len(search_logger_logs) == 3

    search_nonexistent = get_diagnostic_logs(search="nonexistent_needle")
    assert len(search_nonexistent) == 0

    # Test clear
    clear_diagnostic_logs()
    assert len(get_diagnostic_logs()) == 0


def test_ring_buffer_exception_traceback():
    clear_diagnostic_logs()
    test_logger = logging.getLogger("contextcortex.exception_test")
    test_logger.setLevel(logging.INFO)

    try:
        raise ValueError("Simulated diagnostic error")
    except ValueError:
        test_logger.exception("An exception occurred")

    logs = get_diagnostic_logs(limit=5)
    assert len(logs) == 1
    assert logs[0]["traceback"] is not None
    assert "Simulated diagnostic error" in logs[0]["traceback"]
    assert "ValueError" in logs[0]["traceback"]


def test_ring_buffer_emit_exception_handling():
    handler = RingBufferHandler(capacity=10)
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="bad record",
        args=(),
        exc_info=None
    )
    # Patch buffer.append to raise an Exception
    handler.buffer = MagicMock()
    handler.buffer.append.side_effect = RuntimeError("Buffer failure")
    handler.handleError = MagicMock()

    handler.emit(record)
    handler.handleError.assert_called_once_with(record)


def test_logs_api_routes():
    api_app = FastAPI()
    api_app.include_router(router)
    client = TestClient(api_app)
    test_logger = logging.getLogger("contextcortex.api_test")
    test_logger.setLevel(logging.INFO)
    test_logger.info("API test log event")

    res = client.get("/admin/api/logs")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    assert any("API test log event" in l["message"] for l in data)

    # Test with search and level params
    res_filtered = client.get("/admin/api/logs?level=INFO&search=API+test")
    assert res_filtered.status_code == 200
    assert len(res_filtered.json()) >= 1

    # Test DELETE logs
    del_res = client.delete("/admin/api/logs")
    assert del_res.status_code == 200
    assert client.get("/admin/api/logs").json() == []
