import os
import pytest
from app.services.database.engine import get_db_engine, init_db
from app.services.database.connection import (
    get_file_settings,
    set_file_settings,
    get_db_connection,
)
from fastapi.testclient import TestClient

def setup_test_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test_file_settings.db"
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", str(db_file))
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", str(db_file), raising=False)
    engine = get_db_engine(db_url, reset=True)
    init_db(engine=engine)
    return engine


def test_file_summaries_table_has_summary_text_column(tmp_path, monkeypatch):
    setup_test_db(tmp_path, monkeypatch)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cols = [r["name"] for r in cursor.execute("PRAGMA table_info(file_summaries)").fetchall()]
        assert "summary_text" in cols

def test_file_settings_defaults(tmp_path, monkeypatch):
    setup_test_db(tmp_path, monkeypatch)
    settings = get_file_settings()
    assert settings["summary_enabled"] is True
    assert settings["summary_threshold_kb"] == 500
    assert settings["summary_max_file_size_mb"] == 10
    assert settings["read_file_max_lines"] == 2000
    assert isinstance(settings["summary_chat_model"], str)

def test_set_file_settings_persists(tmp_path, monkeypatch):
    setup_test_db(tmp_path, monkeypatch)
    updated = set_file_settings({
        "summary_enabled": False,
        "summary_threshold_kb": 250,
        "summary_max_file_size_mb": 20,
        "read_file_max_lines": 1000,
        "summary_chat_model": "gpt-4o"
    })
    assert updated["summary_enabled"] is False
    assert updated["summary_threshold_kb"] == 250
    assert updated["summary_max_file_size_mb"] == 20
    assert updated["read_file_max_lines"] == 1000
    assert updated["summary_chat_model"] == "gpt-4o"

    loaded = get_file_settings()
    assert loaded["summary_enabled"] is False
    assert loaded["summary_threshold_kb"] == 250
    assert loaded["summary_max_file_size_mb"] == 20
    assert loaded["read_file_max_lines"] == 1000
    assert loaded["summary_chat_model"] == "gpt-4o"

def test_file_settings_api_endpoints(tmp_path, monkeypatch):
    setup_test_db(tmp_path, monkeypatch)
    from main import app
    client = TestClient(app)

    # GET /admin/api/settings/files
    resp = client.get("/admin/api/settings/files")
    assert resp.status_code == 200
    data = resp.json()
    assert data["summary_enabled"] is True
    assert data["summary_threshold_kb"] == 500

    # POST /admin/api/settings/files
    post_resp = client.post("/admin/api/settings/files", json={
        "summary_enabled": True,
        "summary_threshold_kb": 750,
        "summary_max_file_size_mb": 15,
        "read_file_max_lines": 3000,
        "summary_chat_model": "claude-3-5-sonnet"
    })
    assert post_resp.status_code == 200
    assert post_resp.json()["summary_threshold_kb"] == 750

    # Verify GET returns updated
    get_again = client.get("/admin/api/settings/files")
    assert get_again.status_code == 200
    assert get_again.json()["summary_threshold_kb"] == 750
    assert get_again.json()["summary_chat_model"] == "claude-3-5-sonnet"
