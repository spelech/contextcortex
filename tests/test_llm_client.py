from unittest.mock import patch, MagicMock
import pytest

from app.services.database.engine import get_db_engine, init_db
from app.services.database.connection import set_embedding_db_config
from app.services.llm_client import get_llm_extra_headers


@pytest.fixture
def isolated_gateway_db(tmp_path, monkeypatch):
    """Provides a real isolated SQLite database seeded with gateway settings."""
    db_file = tmp_path / "test_llm_gateway.db"
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", str(db_file))
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", str(db_file), raising=False)
    engine = get_db_engine(db_url, reset=True)
    init_db(engine=engine)
    set_embedding_db_config(
        litellm_url="https://gateway.example.com/api/v3",
        litellm_api_key="saved-key",
    )
    return engine


def test_extra_headers_unset(monkeypatch):
    """Verifies that an unset LLM_EXTRA_HEADERS variable returns an empty dictionary."""
    monkeypatch.delenv("LLM_EXTRA_HEADERS", raising=False)
    assert get_llm_extra_headers() == {}


def test_extra_headers_empty(monkeypatch):
    """Verifies that a whitespace-only LLM_EXTRA_HEADERS variable returns an empty dictionary."""
    monkeypatch.setenv("LLM_EXTRA_HEADERS", "   ")
    assert get_llm_extra_headers() == {}


def test_extra_headers_valid_json(monkeypatch):
    """Verifies that valid JSON header objects are normalized to string key-value pairs."""
    monkeypatch.setenv("LLM_EXTRA_HEADERS", '{"X-User-Agent": "contextcortex", "X-User-Name": "jdoe", "X-Count": 3}')
    assert get_llm_extra_headers() == {
        "X-User-Agent": "contextcortex",
        "X-User-Name": "jdoe",
        "X-Count": "3",
    }


def test_extra_headers_invalid_json_logs_warning(monkeypatch, caplog):
    """Verifies that malformed JSON in LLM_EXTRA_HEADERS logs a warning and returns an empty dict."""
    monkeypatch.setenv("LLM_EXTRA_HEADERS", "X-User-Name: jdoe")
    with caplog.at_level("WARNING", logger="contextcortex.llm_client"):
        assert get_llm_extra_headers() == {}
    assert "invalid JSON" in caplog.text


def test_extra_headers_non_object_logs_warning(monkeypatch, caplog):
    """Verifies that non-object JSON values in LLM_EXTRA_HEADERS log a warning and return an empty dict."""
    monkeypatch.setenv("LLM_EXTRA_HEADERS", '["X-User-Name", "jdoe"]')
    with caplog.at_level("WARNING", logger="contextcortex.llm_client"):
        assert get_llm_extra_headers() == {}
    assert "JSON object" in caplog.text


def test_extra_headers_skip_null_and_blank_names(monkeypatch):
    """Verifies that null header values, blank keys, and CR/LF header injection values are omitted."""
    monkeypatch.setenv(
        "LLM_EXTRA_HEADERS",
        '{"X-A": null, " ": "x", "X-Injected": "bad\\r\\nHeader: 1", "X-B": "b"}',
    )
    assert get_llm_extra_headers() == {"X-B": "b"}


def test_vision_ocr_client_uses_saved_settings_and_extra_headers(monkeypatch, isolated_gateway_db):
    """Verifies that PDF vision OCR reads persisted SQLite gateway settings and attaches extra headers."""
    from app.services import pdf_extractor

    monkeypatch.setenv("LLM_EXTRA_HEADERS", '{"X-User-Name": "jdoe"}')
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value.choices = []

    with patch("app.services.pdf_extractor.OpenAI", return_value=mock_client) as mock_openai_cls:
        pdf_extractor._call_vision_ocr(b"png", model_name="vision-model")

    mock_openai_cls.assert_called_once_with(
        base_url="https://gateway.example.com/api/v3",
        api_key="saved-key",
        default_headers={"X-User-Name": "jdoe"},
    )


def test_summarizer_client_sends_extra_headers(monkeypatch, isolated_gateway_db):
    """Verifies that SummarizerService builds its real OpenAI client from SQLite settings and refreshes on rotation."""
    from app.services.summarizer import SummarizerService

    monkeypatch.setenv("LLM_EXTRA_HEADERS", '{"X-User-Name": "jdoe"}')
    service = SummarizerService()
    client = service.client

    assert str(client.base_url).rstrip("/") == "https://gateway.example.com/api/v3"
    assert client.api_key == "saved-key"
    assert client.default_headers.get("X-User-Name") == "jdoe"

    set_embedding_db_config(
        litellm_url="https://gateway-rotated.example.com/api/v3",
        litellm_api_key="rotated-key",
    )
    refreshed = service.client
    assert str(refreshed.base_url).rstrip("/") == "https://gateway-rotated.example.com/api/v3"
    assert refreshed.api_key == "rotated-key"


def test_embeddings_api_client_sends_extra_headers(monkeypatch, isolated_gateway_db):
    """Verifies that API embedding initialization configures OpenAI with persisted settings and extra headers."""
    from app.services import embeddings

    monkeypatch.setenv("LLM_EXTRA_HEADERS", '{"X-User-Agent": "contextcortex"}')
    try:
        embeddings.init_embeddings(provider="api")
        assert embeddings._openai_client is not None
        assert str(embeddings._openai_client.base_url).rstrip("/") == "https://gateway.example.com/api/v3"
        assert embeddings._openai_client.api_key == "saved-key"
        assert embeddings._openai_client.default_headers.get("X-User-Agent") == "contextcortex"
    finally:
        embeddings.init_embeddings(provider="local")
