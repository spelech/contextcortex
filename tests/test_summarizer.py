import os
import pytest
from unittest.mock import MagicMock, patch

from app.services.database.engine import get_db_engine, init_db
from app.services.database.connection import (
    get_db_connection,
    set_file_settings,
    get_file_settings,
)
from app.services.vector_store.base import VectorDocument


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    """Sets up an isolated SQLite database for summarizer testing."""
    db_file = tmp_path / "test_summarizer.db"
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", str(db_file))
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", str(db_file), raising=False)
    engine = get_db_engine(db_url, reset=True)
    init_db(engine=engine)
    return engine


@pytest.fixture
def mock_openai_client():
    """Mocks OpenAI / LiteLLM client for chat completion tests."""
    client = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = (
        "## Summary\n"
        "- **Overview**: Core service handling user authentication and token issuance.\n"
        "- **Key Components**: `AuthService`, `login`, `create_access_token`.\n"
        "- **Dependencies**: Imports JWT validator and database connection."
    )
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    client.chat.completions.create.return_value = mock_response
    return client


def test_generate_file_summary_success(test_db, mock_openai_client):
    from app.services.summarizer import SummarizerService

    service = SummarizerService(client=mock_openai_client)
    filepath = "app/services/auth.py"
    content = "def login(user, pw):\n    return 'token123'\n"

    summary_text, vector_doc = service.generate_file_summary(
        filepath=filepath,
        content=content,
        repo="contextcortex",
        category="auth",
    )

    assert summary_text != ""
    assert "Core service handling user authentication" in summary_text

    # Verify client invocation parameters
    assert mock_openai_client.chat.completions.create.called
    call_kwargs = mock_openai_client.chat.completions.create.call_args.kwargs
    assert "messages" in call_kwargs
    messages = call_kwargs["messages"]
    assert any(m["role"] == "system" for m in messages)
    user_msg = next(m for m in messages if m["role"] == "user")
    assert filepath in user_msg["content"]
    assert "token123" in user_msg["content"]

    # Verify VectorDocument metadata
    assert isinstance(vector_doc, VectorDocument)
    assert vector_doc.doc_type == "summary"
    assert vector_doc.text == summary_text
    assert vector_doc.heading == "Summary"
    assert vector_doc.repo == "contextcortex"
    assert vector_doc.rel_path == filepath
    assert vector_doc.category == "auth"

    payload = vector_doc.to_payload()
    assert payload["doc_type"] == "summary"
    assert payload["heading"] == "Summary"
    assert payload["repo"] == "contextcortex"
    assert payload["rel_path"] == filepath
    assert payload["content"] == summary_text


def test_generate_file_summary_handles_litellm_exception(test_db):
    from app.services.summarizer import SummarizerService

    failing_client = MagicMock()
    failing_client.chat.completions.create.side_effect = RuntimeError("LiteLLM connection timed out")

    service = SummarizerService(client=failing_client)
    summary_text, vector_doc = service.generate_file_summary(
        filepath="app/services/error.py",
        content="x = 1",
        repo="contextcortex",
    )

    # Must not crash, returns empty string or error string, and None vector_doc
    assert vector_doc is None
    assert summary_text == "" or "Error" in summary_text or "failed" in summary_text.lower()


def test_get_or_create_summary_returns_cached_summary(test_db, mock_openai_client):
    from app.services.summarizer import SummarizerService

    filepath = "src/cached_module.py"
    cached_text = "## Cached Markdown Summary\nExisting summary in database."

    # Seed SQLite file_summaries table with cached entry
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO file_summaries (filepath, repo, title, folder, summary_text)
               VALUES (?, ?, ?, ?, ?)""",
            (filepath, "test-repo", "cached_module.py", "src", cached_text),
        )
        conn.commit()

    service = SummarizerService(client=mock_openai_client)
    res = service.get_or_create_summary(filepath=filepath, repo="test-repo", force_refresh=False)

    # Returns cached summary without invoking LiteLLM
    assert res == cached_text
    assert not mock_openai_client.chat.completions.create.called


def test_get_or_create_summary_cache_miss_reads_disk_and_persists(tmp_path, test_db, mock_openai_client):
    from app.services.summarizer import SummarizerService

    test_file = tmp_path / "service_worker.py"
    test_file.write_text("class ServiceWorker:\n    def run(self): pass\n", encoding="utf-8")
    filepath = str(test_file)

    mock_vector_store = MagicMock()
    service = SummarizerService(client=mock_openai_client, vector_store=mock_vector_store)

    res = service.get_or_create_summary(filepath=filepath, repo="test-repo", force_refresh=False)

    # Client was called
    assert mock_openai_client.chat.completions.create.called
    assert "Core service handling user authentication" in res

    # Vector store upsert was triggered
    assert mock_vector_store.upsert_documents.called
    upserted_docs = mock_vector_store.upsert_documents.call_args[0][0]
    assert len(upserted_docs) == 1
    assert upserted_docs[0].doc_type == "summary"

    # SQLite file_summaries was updated
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT summary_text FROM file_summaries WHERE filepath = ?", (filepath,)
        ).fetchone()
        assert row is not None
        assert row["summary_text"] == res


def test_get_or_create_summary_force_refresh_updates_existing_cache(tmp_path, test_db, mock_openai_client):
    from app.services.summarizer import SummarizerService

    test_file = tmp_path / "refresh_target.py"
    test_file.write_text("def refreshed(): pass", encoding="utf-8")
    filepath = str(test_file)

    # Seed old summary
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO file_summaries (filepath, repo, title, folder, summary_text)
               VALUES (?, ?, ?, ?, ?)""",
            (filepath, "test-repo", "refresh_target.py", "", "Old Outdated Summary"),
        )
        conn.commit()

    mock_vector_store = MagicMock()
    service = SummarizerService(client=mock_openai_client, vector_store=mock_vector_store)

    # Calling with force_refresh=True
    res = service.get_or_create_summary(filepath=filepath, repo="test-repo", force_refresh=True)

    assert mock_openai_client.chat.completions.create.called
    assert res != "Old Outdated Summary"
    assert "Core service handling user authentication" in res

    # SQLite was updated with new summary
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT summary_text FROM file_summaries WHERE filepath = ?", (filepath,)
        ).fetchone()
        assert row["summary_text"] == res


def test_get_or_create_summary_litellm_failure_does_not_crash(tmp_path, test_db):
    from app.services.summarizer import SummarizerService

    test_file = tmp_path / "broken_llm.py"
    test_file.write_text("x = 42", encoding="utf-8")

    failing_client = MagicMock()
    failing_client.chat.completions.create.side_effect = Exception("LiteLLM Rate Limit Reached")

    service = SummarizerService(client=failing_client)
    res = service.get_or_create_summary(filepath=str(test_file), repo="test-repo", force_refresh=False)

    assert isinstance(res, str)
    assert res == "" or "error" in res.lower() or "failed" in res.lower()


def test_get_summarizer_service_uses_settings_model(test_db, mock_openai_client):
    from app.services.summarizer import get_summarizer_service, reset_summarizer_service

    reset_summarizer_service()
    set_file_settings({"summary_chat_model": "custom-claude-3-5"})

    service = get_summarizer_service()
    service.client = mock_openai_client

    service.generate_file_summary(filepath="main.py", content="print('hello')", repo="local")

    call_kwargs = mock_openai_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "custom-claude-3-5"

    reset_summarizer_service()


def test_get_or_create_summary_nonexistent_file_raises_not_found(test_db):
    from app.services.summarizer import SummarizerService

    service = SummarizerService()
    with pytest.raises(FileNotFoundError):
        service.get_or_create_summary("/nonexistent/path/to/missing_file.py")


def test_get_or_create_summary_vector_store_failure_resilience(tmp_path, test_db, mock_openai_client):
    from app.services.summarizer import SummarizerService

    test_file = tmp_path / "vs_failure.py"
    test_file.write_text("def test(): pass", encoding="utf-8")

    failing_vs = MagicMock()
    failing_vs.upsert_documents.side_effect = RuntimeError("Qdrant connection lost")

    service = SummarizerService(client=mock_openai_client, vector_store=failing_vs)
    res = service.get_or_create_summary(filepath=str(test_file), repo="test-repo")

    # Summary is still returned and SQLite is updated despite vector store failure
    assert res != ""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT summary_text FROM file_summaries WHERE filepath = ?", (str(test_file),)
        ).fetchone()
        assert row is not None
        assert row["summary_text"] == res


def test_get_or_create_summary_reads_via_file_reader(monkeypatch, test_db, mock_openai_client):
    from app.services.summarizer import SummarizerService

    mock_file_reader = MagicMock()
    mock_file_reader.read_file.return_value = {
        "filepath": "virtual/file.py",
        "content": "class VirtualFile: pass\n",
        "total_lines": 1,
    }

    mock_get_reader = MagicMock(return_value=mock_file_reader)
    import sys
    import types
    fake_fr_module = types.ModuleType("app.services.file_reader")
    fake_fr_module.get_file_reader_service = mock_get_reader
    monkeypatch.setitem(sys.modules, "app.services.file_reader", fake_fr_module)

    service = SummarizerService(client=mock_openai_client)
    res = service.get_or_create_summary(filepath="virtual/file.py", repo="custom-repo")

    assert mock_file_reader.read_file.called
    assert res != ""


def test_generate_file_summary_truncates_huge_content(test_db, mock_openai_client):
    from app.services.summarizer import SummarizerService

    service = SummarizerService(client=mock_openai_client)
    huge_content = "def func():\n    pass\n" * 20000  # > 200k chars

    summary_text, vector_doc = service.generate_file_summary(
        filepath="large_module.py",
        content=huge_content,
        repo="local",
    )

    assert mock_openai_client.chat.completions.create.called
    call_kwargs = mock_openai_client.chat.completions.create.call_args.kwargs
    user_msg = next(m for m in call_kwargs["messages"] if m["role"] == "user")
    assert "truncated for LLM context ceiling" in user_msg["content"]
    assert len(user_msg["content"]) < len(huge_content)

