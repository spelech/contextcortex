import pytest
import logging
from app.services.logger import RingBufferHandler, get_diagnostic_logs, clear_diagnostic_logs
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.routes import router


def test_ring_buffer_logging():
    clear_diagnostic_logs()
    test_logger = logging.getLogger("notes-rag-mcp.test")
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

    # Test clear
    clear_diagnostic_logs()
    assert len(get_diagnostic_logs()) == 0

def test_logs_api_routes():
    api_app = FastAPI()
    api_app.include_router(router)
    client = TestClient(api_app)
    test_logger = logging.getLogger("notes-rag-mcp.api_test")
    test_logger.setLevel(logging.INFO)
    test_logger.info("API test log event")

    res = client.get("/admin/api/logs")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    assert any("API test log event" in l["message"] for l in data)

    # Test DELETE logs
    del_res = client.delete("/admin/api/logs")
    assert del_res.status_code == 200
    assert client.get("/admin/api/logs").json() == []
