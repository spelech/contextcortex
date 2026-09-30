import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.routes import router
import app.services.database as db_service

app = FastAPI()
app.include_router(router)


@pytest.fixture
def mock_db(tmp_path):
    import sqlite3
    from unittest.mock import patch
    db_file = str(tmp_path / "test_ai_gateway.db")
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE system_metadata (key TEXT PRIMARY KEY, value TEXT);
    """)
    conn.commit()
    conn.close()

    with patch("app.services.database.get_db_connection") as mock_conn:
        def get_conn():
            c = sqlite3.connect(db_file)
            c.row_factory = sqlite3.Row
            return c
        mock_conn.side_effect = get_conn
        yield db_file


client = TestClient(app)

def test_ai_gateway_settings_lifecycle(mock_db):
    """Verify OpenAI-compatible AI Gateway configuration lifecycle and masking."""
    # 1. Initial read
    resp = client.get("/admin/api/settings/ai-gateway")
    assert resp.status_code == 200
    data = resp.json()
    assert "url" in data
    assert "has_api_key" in data
    assert "masked_api_key" in data
    assert "chat_model" in data
    assert "vision_ocr_model" in data
    assert "embedding_model" in data

    # 2. Update settings with new key
    payload = {
        "url": "http://litellm-cluster:4000/v1",
        "api_key": "sk-secret9988776655",
        "chat_model": "gpt-4o",
        "vision_ocr_model": "gpt-4o-mini",
        "embedding_model": "text-embedding-3-small"
    }
    update_resp = client.post("/admin/api/settings/ai-gateway", json=payload)
    assert update_resp.status_code == 200
    res_data = update_resp.json()
    assert res_data["status"] == "success"
    cfg = res_data["config"]
    assert cfg["url"] == "http://litellm-cluster:4000/v1"
    assert cfg["has_api_key"] is True
    assert cfg["masked_api_key"].startswith("sk-")
    assert "9988776655" not in cfg["masked_api_key"]
    assert cfg["chat_model"] == "gpt-4o"
    assert cfg["vision_ocr_model"] == "gpt-4o-mini"
    assert cfg["embedding_model"] == "text-embedding-3-small"

    # 3. Read back to confirm persistence in SQLite
    read_resp = client.get("/admin/api/settings/ai-gateway")
    assert read_resp.status_code == 200
    read_cfg = read_resp.json()
    assert read_cfg["url"] == "http://litellm-cluster:4000/v1"
    assert read_cfg["has_api_key"] is True
    assert read_cfg["chat_model"] == "gpt-4o"

    # 4. Verify embedding settings update does NOT wipe AI Gateway config
    emb_payload = {
        "provider": "local",
        "threads": 4,
        "batch_size": 64,
        "dense_model": "BAAI/bge-small-en-v1.5",
        "sparse_model": "Qdrant/bm25"
    }
    emb_resp = client.post("/admin/api/settings/embedding", json=emb_payload)
    assert emb_resp.status_code == 200

    read_again = client.get("/admin/api/settings/ai-gateway").json()
    assert read_again["url"] == "http://litellm-cluster:4000/v1"
    assert read_again["has_api_key"] is True
    assert read_again["chat_model"] == "gpt-4o"
