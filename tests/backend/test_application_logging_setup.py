"""
Application logging setup: INFO lines from 'contextcortex.*' loggers must reach stdout
(the portable log file) and the diagnostic ring buffer (GET /admin/api/logs).
"""

import io
import logging

import pytest

from app.services import logger as log_service


def _console_handlers():
    return [h for h in logging.getLogger().handlers if getattr(h, log_service._CONSOLE_MARKER, False)]


@pytest.fixture
def captured_console():
    import main  # noqa: F401  # imports the app the same way the server entry point does

    handlers = _console_handlers()
    assert len(handlers) == 1
    console = handlers[0]
    buffer = io.StringIO()
    original = console.setStream(buffer)
    log_service.clear_diagnostic_logs()
    try:
        yield buffer
    finally:
        console.setStream(original)
        log_service.clear_diagnostic_logs()


def test_indexer_info_reaches_stdout_and_diagnostic_buffer(captured_console):
    logging.getLogger("contextcortex.indexer").info("Scanning local paths for logging test")

    console_text = captured_console.getvalue()
    assert "Scanning local paths for logging test" in console_text
    assert console_text.count("Scanning local paths for logging test") == 1
    assert "[INFO] contextcortex.indexer:" in console_text

    entries = log_service.get_diagnostic_logs(search="Scanning local paths for logging test")
    assert len(entries) == 1
    assert entries[0]["level"] == "INFO"
    assert entries[0]["logger"] == "contextcortex.indexer"


def test_configure_application_logging_is_idempotent(captured_console):
    log_service.configure_application_logging()
    log_service.configure_application_logging()
    assert len(_console_handlers()) == 1
    assert logging.getLogger().handlers.count(log_service._diagnostic_handler) == 1

    logging.getLogger("contextcortex.indexer").info("Logged once only")
    assert captured_console.getvalue().count("Logged once only") == 1


def test_third_party_info_is_not_printed(captured_console):
    logging.getLogger("httpx").info("HTTP Request: POST https://example.invalid")
    assert "example.invalid" not in captured_console.getvalue()


def test_log_level_env_controls_application_level(monkeypatch, captured_console):
    app_logger = logging.getLogger(log_service.APP_LOGGER_NAME)
    root = logging.getLogger()
    old_app_level, old_root_level = app_logger.level, root.level
    try:
        monkeypatch.setenv("LOG_LEVEL", "WARNING")
        log_service.configure_application_logging()
        logging.getLogger("contextcortex.indexer").info("Hidden at WARNING")
        assert "Hidden at WARNING" not in captured_console.getvalue()

        monkeypatch.setenv("LOG_LEVEL", "debug")
        log_service.configure_application_logging()
        assert app_logger.level == logging.DEBUG
    finally:
        app_logger.setLevel(old_app_level)
        root.setLevel(old_root_level)


@pytest.mark.parametrize(
    "value, expected",
    [("", logging.INFO), ("info", logging.INFO), ("ERROR", logging.ERROR), ("15", 15), ("bogus", logging.INFO)],
)
def test_resolve_log_level(value, expected):
    assert log_service.resolve_log_level(value) == expected
