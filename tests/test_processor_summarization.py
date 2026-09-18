import os
import json
import pytest
from unittest.mock import patch, MagicMock

from app.services.database.engine import get_db_engine, init_db
from app.services.database.connection import get_db_connection, set_file_settings
from app.services.indexing.processor import process_file_content

@pytest.fixture
def test_env(tmp_path, monkeypatch):
    db_file = tmp_path / "test_proc_summary.db"
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", str(db_file))
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", str(db_file), raising=False)

    engine = get_db_engine(db_url, reset=True)
    init_db(engine=engine)

    from app.services.summarizer import reset_summarizer_service
    reset_summarizer_service()

    # Set threshold to 10 KB for easy testing
    set_file_settings({
        "summary_enabled": True,
        "summary_threshold_kb": 10,
        "summary_max_file_size_mb": 5,
        "read_file_max_lines": 2000
    })

    return tmp_path


def test_large_file_auto_summarization(test_env):
    # Create content larger than 10 KB (e.g. 15 KB)
    large_content = "def calculate_data():\n    return 42\n" * 500
    assert len(large_content.encode("utf-8")) > 10 * 1024

    fake_resp = MagicMock()
    fake_resp.choices = [MagicMock(message=MagicMock(content="## Executive Overview\nCalculates data."))]

    with patch("app.services.summarizer.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = fake_resp
        mock_openai_cls.return_value = mock_client

        with patch("app.services.embeddings.get_hybrid_embeddings") as mock_embed:
            mock_embed.return_value = {"dense": [0.1] * 384, "sparse": None}

            points, symbols, summary_tuple, rels, routes, calls = process_file_content(
                filepath="/path/to/large_file.py",
                rel_path="large_file.py",
                content=large_content,
                repo="test_repo",
                doc_type="code"
            )

            # Should contain a summary vector document
            assert len(points) == 1
            assert points[0].doc_type == "summary"
            assert "Calculates data." in points[0].text

            # summary_tuple should contain the summary text
            # summary_tuple: (filepath, repo, title, folder, category, tags, headings, keywords, summary_text, mtime)
            assert len(summary_tuple) == 10
            summary_text = summary_tuple[8]
            assert "Calculates data." in summary_text


def test_large_file_disabled_summarization(test_env):
    set_file_settings({"summary_enabled": False})

    large_content = "def calculate_data():\n    return 42\n" * 500
    points, symbols, summary_tuple, rels, routes, calls = process_file_content(
        filepath="/path/to/large_file.py",
        rel_path="large_file.py",
        content=large_content,
        repo="test_repo",
        doc_type="code"
    )

    assert len(points) == 0
    assert len(summary_tuple) == 10
    assert summary_tuple[8] is None
