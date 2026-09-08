import os
import pytest
from app.services.database.engine import get_db_engine, init_db
from app.services.database.connection import (
    get_metadata,
    get_embedding_db_config,
    set_embedding_db_config,
)

def setup_test_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_models.db"
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    engine = get_db_engine(db_url, reset=True)
    init_db(engine=engine)
    return engine


def test_embedding_db_config_defaults(tmp_path, monkeypatch):
    # Ensure env vars are cleared
    monkeypatch.delenv("VISION_OCR_MODEL", raising=False)
    monkeypatch.delenv("CHAT_MODEL", raising=False)
    setup_test_db(tmp_path, monkeypatch)

    from app.services.database import get_vision_ocr_model, get_chat_model

    cfg = get_embedding_db_config()
    assert "vision_ocr_model" in cfg
    assert "chat_model" in cfg
    assert cfg["vision_ocr_model"] == "gemini-2.5-flash"
    assert cfg["chat_model"] == "gemini-2.5-flash"

    assert get_vision_ocr_model() == "gemini-2.5-flash"
    assert get_chat_model() == "gemini-2.5-flash"


def test_env_variable_fallbacks(tmp_path, monkeypatch):
    monkeypatch.setenv("VISION_OCR_MODEL", "custom-ocr-env")
    monkeypatch.setenv("CHAT_MODEL", "custom-chat-env")
    setup_test_db(tmp_path, monkeypatch)

    from app.services.database import get_vision_ocr_model, get_chat_model

    cfg = get_embedding_db_config()
    assert cfg["vision_ocr_model"] == "custom-ocr-env"
    assert cfg["chat_model"] == "custom-chat-env"

    assert get_vision_ocr_model() == "custom-ocr-env"
    assert get_chat_model() == "custom-chat-env"


def test_set_embedding_db_config_persists_to_system_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv("VISION_OCR_MODEL", "fallback-vision")
    monkeypatch.setenv("CHAT_MODEL", "fallback-chat")
    setup_test_db(tmp_path, monkeypatch)

    from app.services.database import get_vision_ocr_model, get_chat_model

    set_embedding_db_config(
        vision_ocr_model="db-persisted-vision",
        chat_model="db-persisted-chat",
    )

    # Check system_metadata persistence
    assert get_metadata("vision_ocr_model") == "db-persisted-vision" or get_metadata("embedding_vision_ocr_model") == "db-persisted-vision"
    assert get_metadata("chat_model") == "db-persisted-chat" or get_metadata("embedding_chat_model") == "db-persisted-chat"

    # Check config retrieval
    cfg = get_embedding_db_config()
    assert cfg["vision_ocr_model"] == "db-persisted-vision"
    assert cfg["chat_model"] == "db-persisted-chat"

    # Check accessor functions prioritize DB over environment
    assert get_vision_ocr_model() == "db-persisted-vision"
    assert get_chat_model() == "db-persisted-chat"


def test_update_embedding_config_service(tmp_path, monkeypatch):
    setup_test_db(tmp_path, monkeypatch)

    from app.services.embeddings import update_embedding_config, get_embedding_config

    updated = update_embedding_config(
        vision_ocr_model="service-ocr-model",
        chat_model="service-chat-model",
    )

    assert updated.get("vision_ocr_model") == "service-ocr-model"
    assert updated.get("chat_model") == "service-chat-model"

    active_cfg = get_embedding_config()
    assert active_cfg.get("vision_ocr_model") == "service-ocr-model"
    assert active_cfg.get("chat_model") == "service-chat-model"
