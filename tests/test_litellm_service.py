import os
import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock

from app.services.litellm_service import discover_models


@pytest.mark.asyncio
async def test_discover_models_success():
    mock_payload = {
        "data": [
            {"id": "gemini-embedding-2", "mode": "embedding", "owned_by": "openai"},
            {"id": "text-embedding-3-small", "mode": "embedding", "owned_by": "openai"},
            {"id": "bge-m3", "mode": "embedding", "owned_by": "local"},
            {"id": "gemini-2.5-flash", "mode": "chat", "owned_by": "google"},
            {"id": "qwen3-vl-32b-instruct", "mode": "chat", "owned_by": "alibaba"},
            {"id": "gemini-2.5-pro", "mode": "chat", "owned_by": "google"},
            {"id": "deepseek-v3.2", "mode": "chat", "owned_by": "deepseek"},
            {"id": "dall-e-3", "mode": "image_generation", "owned_by": "openai"},
        ],
        "object": "list",
    }

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = mock_payload
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response

        res = await discover_models(
            url="http://litellm-test:4000/v1",
            api_key="sk-test-key",
        )

        assert res["status"] == "success"
        assert res["total_models"] == 8
        assert len(res["models"]) == 8

        # Embedding models check
        assert "gemini-embedding-2" in res["embedding_models"]
        assert "text-embedding-3-small" in res["embedding_models"]
        assert "bge-m3" in res["embedding_models"]
        assert "gemini-2.5-flash" not in res["embedding_models"]

        # Vision models check
        assert "gemini-2.5-flash" in res["vision_models"]
        assert "qwen3-vl-32b-instruct" in res["vision_models"]
        assert "gemini-2.5-pro" in res["vision_models"]
        assert "deepseek-v3.2" not in res["vision_models"]
        assert "gemini-embedding-2" not in res["vision_models"]
        assert "dall-e-3" not in res["vision_models"]

        # Chat models check
        assert "gemini-2.5-flash" in res["chat_models"]
        assert "gemini-2.5-pro" in res["chat_models"]
        assert "deepseek-v3.2" in res["chat_models"]
        assert "qwen3-vl-32b-instruct" in res["chat_models"]
        assert "gemini-embedding-2" not in res["chat_models"]
        assert "dall-e-3" not in res["chat_models"]

        # Sorting check
        assert res["embedding_models"] == sorted(res["embedding_models"])
        assert res["vision_models"] == sorted(res["vision_models"])
        assert res["chat_models"] == sorted(res["chat_models"])

        # Request check
        mock_get.assert_called_once()
        args, kwargs = mock_get.call_args
        assert args[0] == "http://litellm-test:4000/v1/models"
        assert kwargs["headers"]["Authorization"] == "Bearer sk-test-key"


@pytest.mark.asyncio
async def test_discover_models_timeout():
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.TimeoutException("Connection timed out after 6.0s")

        res = await discover_models(url="http://litellm-timeout:4000/v1", api_key="sk-test")

        assert res["status"] == "error"
        assert "timed out" in res["message"].lower() or "timeout" in res["message"].lower()
        assert res["models"] == []
        assert res["embedding_models"] == []
        assert res["vision_models"] == []
        assert res["chat_models"] == []


@pytest.mark.asyncio
async def test_discover_models_connect_error():
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.ConnectError("Failed to establish connection")

        res = await discover_models(url="http://litellm-unreachable:4000/v1", api_key="sk-test")

        assert res["status"] == "error"
        assert "connect" in res["message"].lower() or "connection" in res["message"].lower()
        assert res["models"] == []
        assert res["embedding_models"] == []
        assert res["vision_models"] == []
        assert res["chat_models"] == []


@pytest.mark.asyncio
async def test_discover_models_http_401_unauthorized():
    mock_request = httpx.Request("GET", "http://litellm:4000/v1/models")
    mock_response = httpx.Response(status_code=401, request=mock_request, text="Unauthorized: Invalid API Key")

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response

        res = await discover_models(url="http://litellm:4000/v1", api_key="bad-key")

        assert res["status"] == "error"
        assert "401" in res["message"] or "unauthorized" in res["message"].lower()
        assert res["models"] == []
        assert res["embedding_models"] == []
        assert res["vision_models"] == []
        assert res["chat_models"] == []


@pytest.mark.asyncio
async def test_discover_models_http_500_error():
    mock_request = httpx.Request("GET", "http://litellm:4000/v1/models")
    mock_response = httpx.Response(status_code=500, request=mock_request, text="Internal Server Error")

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response

        res = await discover_models(url="http://litellm:4000/v1", api_key="test-key")

        assert res["status"] == "error"
        assert "500" in res["message"]
        assert res["models"] == []


@pytest.mark.asyncio
async def test_discover_models_url_normalization():
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": []}
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response

        # Test with trailing slashes and without /v1
        await discover_models(url="http://litellm:4000/", api_key="dummy")
        args, _ = mock_get.call_args
        assert args[0] == "http://litellm:4000/v1/models"

        # Test with /v1/ trailing slash
        await discover_models(url="http://litellm:4000/v1/", api_key="dummy")
        args, _ = mock_get.call_args
        assert args[0] == "http://litellm:4000/v1/models"

        # Test with already full /models path
        await discover_models(url="http://litellm:4000/v1/models", api_key="dummy")
        args, _ = mock_get.call_args
        assert args[0] == "http://litellm:4000/v1/models"


@pytest.mark.asyncio
async def test_discover_models_default_resolution(monkeypatch):
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": [{"id": "model-1", "mode": "chat"}]}
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response

        with patch("app.services.litellm_service.get_embedding_db_config") as mock_db_cfg:
            mock_db_cfg.return_value = {
                "litellm_url": "http://custom-db-litellm:4000/v1",
                "litellm_api_key": "db-secret-key",
            }

            res = await discover_models()
            assert res["status"] == "success"
            args, kwargs = mock_get.call_args
            assert args[0] == "http://custom-db-litellm:4000/v1/models"
            assert kwargs["headers"]["Authorization"] == "Bearer db-secret-key"
