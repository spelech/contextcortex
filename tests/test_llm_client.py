from unittest.mock import patch, MagicMock

from app.services.llm_client import get_llm_extra_headers


def test_extra_headers_unset(monkeypatch):
    monkeypatch.delenv("LLM_EXTRA_HEADERS", raising=False)
    assert get_llm_extra_headers() == {}


def test_extra_headers_empty(monkeypatch):
    monkeypatch.setenv("LLM_EXTRA_HEADERS", "   ")
    assert get_llm_extra_headers() == {}


def test_extra_headers_valid_json(monkeypatch):
    monkeypatch.setenv("LLM_EXTRA_HEADERS", '{"X-User-Agent": "contextcortex", "X-User-Name": "jdoe", "X-Count": 3}')
    assert get_llm_extra_headers() == {
        "X-User-Agent": "contextcortex",
        "X-User-Name": "jdoe",
        "X-Count": "3",
    }


def test_extra_headers_invalid_json_logs_warning(monkeypatch, caplog):
    monkeypatch.setenv("LLM_EXTRA_HEADERS", "X-User-Name: jdoe")
    with caplog.at_level("WARNING", logger="contextcortex.llm_client"):
        assert get_llm_extra_headers() == {}
    assert "invalid JSON" in caplog.text


def test_extra_headers_non_object_logs_warning(monkeypatch, caplog):
    monkeypatch.setenv("LLM_EXTRA_HEADERS", '["X-User-Name", "jdoe"]')
    with caplog.at_level("WARNING", logger="contextcortex.llm_client"):
        assert get_llm_extra_headers() == {}
    assert "JSON object" in caplog.text


def test_extra_headers_skip_null_and_blank_names(monkeypatch):
    monkeypatch.setenv("LLM_EXTRA_HEADERS", '{"X-A": null, " ": "x", "X-B": "b"}')
    assert get_llm_extra_headers() == {"X-B": "b"}


def test_vision_ocr_client_uses_saved_settings_and_extra_headers(monkeypatch):
    from app.services import pdf_extractor

    monkeypatch.setenv("LLM_EXTRA_HEADERS", '{"X-User-Name": "jdoe"}')
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value.choices = []

    db_cfg = {"litellm_url": "https://gateway.example.com/api/v3", "litellm_api_key": "saved-key"}
    with patch("app.services.pdf_extractor.get_embedding_db_config", return_value=db_cfg), \
         patch("app.services.pdf_extractor.OpenAI", return_value=mock_client) as mock_openai_cls:
        pdf_extractor._call_vision_ocr(b"png", model_name="vision-model")

    mock_openai_cls.assert_called_once_with(
        base_url="https://gateway.example.com/api/v3",
        api_key="saved-key",
        default_headers={"X-User-Name": "jdoe"},
    )


def test_summarizer_client_sends_extra_headers(monkeypatch):
    from app.services.summarizer import SummarizerService

    monkeypatch.setenv("LLM_EXTRA_HEADERS", '{"X-User-Name": "jdoe"}')
    db_cfg = {"litellm_url": "https://gateway.example.com/api/v3", "litellm_api_key": "saved-key"}
    with patch("app.services.summarizer.get_embedding_db_config", return_value=db_cfg), \
         patch("app.services.summarizer.OpenAI") as mock_openai_cls:
        _ = SummarizerService().client

    mock_openai_cls.assert_called_once_with(
        base_url="https://gateway.example.com/api/v3",
        api_key="saved-key",
        default_headers={"X-User-Name": "jdoe"},
    )
