import pytest
from unittest.mock import patch, AsyncMock
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)


def test_api_discover_models_endpoint():
    mock_discovery_result = {
        "status": "success",
        "total_models": 3,
        "models": [
            {"id": "gemini-embedding-2", "mode": "embedding"},
            {"id": "gemini-2.5-flash", "mode": "chat"},
            {"id": "qwen3-vl-32b-instruct", "mode": "chat"},
        ],
        "embedding_models": ["gemini-embedding-2"],
        "vision_models": ["gemini-2.5-flash", "qwen3-vl-32b-instruct"],
        "chat_models": ["gemini-2.5-flash", "qwen3-vl-32b-instruct"],
    }

    with patch("app.services.litellm_service.discover_models", new_callable=AsyncMock, return_value=mock_discovery_result):
        resp = client.get("/admin/api/models/discover?url=http://custom:4000/v1&api_key=sk-custom")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "gemini-embedding-2" in data["embedding_models"]
        assert "gemini-2.5-flash" in data["vision_models"]


def test_api_embedding_settings_get_and_post_with_models(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_models.db")
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", test_db)
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", test_db)

    from app.services.database.connection import init_db
    init_db()

    # 1. GET embedding settings
    get_resp = client.get("/admin/api/settings/embedding")
    assert get_resp.status_code == 200
    cfg = get_resp.json()
    assert "vision_ocr_model" in cfg
    assert "chat_model" in cfg

    # 2. POST embedding settings with vision_ocr_model and chat_model
    post_payload = {
        "provider": "api",
        "dense_model": "gemini-embedding-2",
        "sparse_model": "Qdrant/bm25",
        "threads": 4,
        "batch_size": 64,
        "litellm_url": "http://litellm:4000/v1",
        "litellm_api_key": "sk-test-key",
        "vision_ocr_model": "gemini-2.5-flash",
        "chat_model": "gemini-2.5-pro",
    }

    post_resp = client.post("/admin/api/settings/embedding", json=post_payload)
    assert post_resp.status_code == 200
    res = post_resp.json()
    assert res["status"] == "success"
    saved = res["config"]
    assert saved["provider"] == "api"
    assert saved["dense_model"] == "gemini-embedding-2"
    assert saved["vision_ocr_model"] == "gemini-2.5-flash"
    assert saved["chat_model"] == "gemini-2.5-pro"

    # 3. Verify GET returns updated configuration
    verify_resp = client.get("/admin/api/settings/embedding")
    assert verify_resp.status_code == 200
    vcfg = verify_resp.json()
    assert vcfg["vision_ocr_model"] == "gemini-2.5-flash"
    assert vcfg["chat_model"] == "gemini-2.5-pro"
