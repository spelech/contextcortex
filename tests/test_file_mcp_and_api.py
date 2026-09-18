import os
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.services.database.engine import get_db_engine, init_db
from app.services.database.connection import get_db_connection
from app.services.file_reader import get_file_reader_service, reset_file_reader_service
from app.services.summarizer import get_summarizer_service, reset_summarizer_service
from app.mcp.handlers.file_handlers import handle_read_file, handle_summarize_file
from main import app

@pytest.fixture
def test_env(tmp_path, monkeypatch):
    db_file = tmp_path / "test_mcp_api.db"
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", str(db_file))
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", str(db_file), raising=False)

    storage_dir = tmp_path / "storage"
    storage_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LOCAL_STORAGE_PATH", str(storage_dir))

    watched_dir = tmp_path / "watched"
    watched_dir.mkdir(parents=True, exist_ok=True)

    engine = get_db_engine(db_url, reset=True)
    init_db(engine=engine)

    # Register watched path
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO indexed_paths (path, type, recursive, enabled, category, repo) VALUES (?, ?, 1, 1, 'watched', 'watched_repo')",
            (str(watched_dir), "directory")
        )
        conn.commit()

    reset_file_reader_service()
    reset_summarizer_service()

    client = TestClient(app)
    return {
        "storage_dir": storage_dir,
        "watched_dir": watched_dir,
        "client": client
    }


@pytest.mark.asyncio
async def test_mcp_handle_read_file(test_env):
    watched_dir = test_env["watched_dir"]
    sample_file = watched_dir / "example.py"
    sample_file.write_text("line 1\nline 2\nline 3\nline 4\nline 5\n", encoding="utf-8")

    # Read slice lines 2 to 4
    output = await handle_read_file("example.py", repo="watched_repo", start_line=2, end_line=4)
    assert "lines 2-4 of 5" in output
    assert "line 2\nline 3\nline 4" in output

    # Path traversal rejected
    err_output = await handle_read_file("../../../etc/passwd")
    assert "Forbidden" in err_output or "Error" in err_output


@pytest.mark.asyncio
async def test_mcp_handle_summarize_file(test_env):
    watched_dir = test_env["watched_dir"]
    sample_file = watched_dir / "large.py"
    sample_file.write_text("def hello():\n    return 'world'\n", encoding="utf-8")

    fake_resp = MagicMock()
    fake_resp.choices = [MagicMock(message=MagicMock(content="## Executive Overview\nA test module."))]

    with patch("app.services.summarizer.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = fake_resp
        mock_openai_cls.return_value = mock_client
        reset_summarizer_service()

        output = await handle_summarize_file(str(sample_file))
        assert "## Executive Overview" in output
        assert "A test module." in output


def test_api_read_file(test_env):
    client = test_env["client"]
    watched_dir = test_env["watched_dir"]
    sample_file = watched_dir / "api_test.txt"
    sample_file.write_text("alpha\nbeta\ngamma\ndelta\n", encoding="utf-8")

    resp = client.get(f"/admin/api/files/read?path={sample_file}&start_line=1&end_line=2")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_lines"] == 4
    assert data["content"] == "alpha\nbeta"
    assert data["start_line"] == 1
    assert data["end_line"] == 2


def test_api_summarize_file(test_env):
    client = test_env["client"]
    watched_dir = test_env["watched_dir"]
    sample_file = watched_dir / "api_summary.txt"
    sample_file.write_text("important content here", encoding="utf-8")

    fake_resp = MagicMock()
    fake_resp.choices = [MagicMock(message=MagicMock(content="Mocked summary response"))]

    with patch("app.services.summarizer.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = fake_resp
        mock_openai_cls.return_value = mock_client
        reset_summarizer_service()

        resp = client.post("/admin/api/files/summarize", json={
            "path": str(sample_file),
            "force_refresh": True
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "Mocked summary response" in data["summary"]
