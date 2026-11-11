import os
import json
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.services.database.engine import get_db_engine, init_db
from app.services.database.connection import get_db_connection
from app.services.file_reader import FileReaderService, reset_file_reader_service, get_file_reader_service
from app.mcp.handlers.file_handlers import handle_grep_code
from app.mcp.mcp_server import mcp_server
from app.services.vector_store.pgvector_store import PgVectorStore
from app.services.vector_store.qdrant_store import QdrantVectorStore
from main import app


@pytest.fixture
def grep_test_env(tmp_path, monkeypatch):
    db_file = tmp_path / "test_grep.db"
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", str(db_file))
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", str(db_file), raising=False)

    storage_dir = tmp_path / "storage"
    storage_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LOCAL_STORAGE_PATH", str(storage_dir))

    watched_dir = tmp_path / "repo_auth"
    watched_dir.mkdir(parents=True, exist_ok=True)

    engine = get_db_engine(db_url, reset=True)
    init_db(engine=engine)

    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO indexed_paths (path, type, recursive, enabled, category, repo) VALUES (?, ?, 1, 1, 'code', 'auth-service')",
            (str(watched_dir), "directory")
        )
        conn.execute(
            """
            INSERT INTO git_repositories (name, url, branch, commit_sha, provider, enabled)
            VALUES ('auth-service', 'https://github.com/org/auth-service', 'main', 'abc1234', 'github', 1)
            """
        )
        conn.commit()

    reset_file_reader_service()
    client = TestClient(app)

    return {
        "db_url": db_url,
        "engine": engine,
        "storage_dir": storage_dir,
        "watched_dir": watched_dir,
        "client": client,
    }


def test_file_reader_reconstruction_overlapping_chunks_qdrant(tmp_path, monkeypatch):
    """Verifies FileReaderService._read_from_vector_store reconstructs overlapping chunks with exact line numbers on QdrantStore."""
    db_file = tmp_path / "test_qdrant_recon.db"
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    engine = get_db_engine(db_url, reset=True)
    init_db(engine=engine)

    mock_qdrant = MagicMock(spec=QdrantVectorStore)
    # Overlapping chunks: chunk1 is lines 1-3, chunk2 is lines 2-5
    chunk1 = {
        "repo": "remote-repo",
        "path": "src/app.py",
        "rel_path": "src/app.py",
        "start_line": 1,
        "end_line": 3,
        "content": "line 1: def main():\nline 2:     x = 1\nline 3:     y = 2"
    }
    chunk2 = {
        "repo": "remote-repo",
        "path": "src/app.py",
        "rel_path": "src/app.py",
        "start_line": 2,
        "end_line": 5,
        "content": "line 2:     x = 1\nline 3:     y = 2\nline 4:     z = 3\nline 5:     return z"
    }
    mock_qdrant.get_file_chunks.return_value = [chunk1, chunk2]

    with patch("app.services.vector_store.get_vector_store", return_value=mock_qdrant):
        service = FileReaderService(storage_root=str(tmp_path))
        # Reading non-existent disk file should fall back to vector store
        res = service.read_file("src/app.py", repo="remote-repo")

        assert res["source"] == "vector_store"
        assert res["total_lines"] == 5
        assert res["start_line"] == 1
        assert res["end_line"] == 5
        expected_lines = [
            "line 1: def main():",
            "line 2:     x = 1",
            "line 3:     y = 2",
            "line 4:     z = 3",
            "line 5:     return z"
        ]
        assert res["content"] == "\n".join(expected_lines)


def test_file_reader_reconstruction_overlapping_chunks_pgvector(tmp_path, monkeypatch):
    """Verifies FileReaderService._read_from_vector_store reconstructs overlapping chunks with exact line numbers on PgVectorStore."""
    db_file = tmp_path / "test_pg_recon.db"
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    engine = get_db_engine(db_url, reset=True)
    init_db(engine=engine)

    pg_store = PgVectorStore(engine=engine, collection_name="test_recon_coll")
    
    docs = [
        {
            "id": "c1",
            "repo": "pg-repo",
            "path": "server.py",
            "rel_path": "server.py",
            "start_line": 1,
            "end_line": 2,
            "content": "from fastapi import FastAPI\napp = FastAPI()"
        },
        {
            "id": "c2",
            "repo": "pg-repo",
            "path": "server.py",
            "rel_path": "server.py",
            "start_line": 2,
            "end_line": 4,
            "content": "app = FastAPI()\n\n@app.get('/')"
        }
    ]
    pg_store.upsert_documents(docs)

    with patch("app.services.vector_store.get_vector_store", return_value=pg_store):
        service = FileReaderService(storage_root=str(tmp_path))
        res = service.read_file("server.py", repo="pg-repo")

        assert res["source"] == "vector_store"
        assert res["total_lines"] == 4
        expected = "from fastapi import FastAPI\napp = FastAPI()\n\n@app.get('/')"
        assert res["content"] == expected


def test_grep_code_literal_and_case_sensitivity(grep_test_env):
    watched_dir = grep_test_env["watched_dir"]
    sub_dir = watched_dir / "app" / "services"
    sub_dir.mkdir(parents=True, exist_ok=True)
    sample_file = sub_dir / "jwt_validator.py"

    code_text = (
        "import jwt\n"
        "from exceptions import InvalidTokenError\n"
        "\n"
        "class JWTValidator:\n"
        "    def verify_token(self, token):\n"
        "        if payload['exp'] < now:\n"
        "            logger.warning('Expired JWT')\n"
        "            raise InvalidTokenError('Token expired')\n"
        "        return payload\n"
    )
    sample_file.write_text(code_text, encoding="utf-8")

    # Add AST symbol in SQLite
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language)
            VALUES ('auth-service', 'app/services/jwt_validator.py', 'verify_token', 'JWTValidator.verify_token', 'method', 5, 9, 'def verify_token(self, token)', 'python')
            """
        )
        conn.commit()

    service = get_file_reader_service()

    # 1. Exact case-insensitive match
    res_ci = service.grep_code(pattern="invalidtokenerror", case_sensitive=False, context_lines=2)
    assert res_ci["total_matches"] == 2
    assert res_ci["matches"][0]["line"] == 2
    assert res_ci["matches"][1]["line"] == 8
    assert res_ci["matches"][1]["symbol"] == "JWTValidator.verify_token"
    assert res_ci["matches"][1]["kind"] == "method"
    assert res_ci["matches"][1]["permalink"] == "https://github.com/org/auth-service/blob/abc1234/app/services/jwt_validator.py#L8"

    # Verify context window
    ctx = res_ci["matches"][1]["context"]
    assert any(c["line"] == 7 and "logger.warning" in c["text"] for c in ctx)
    assert any(c["line"] == 8 and "raise InvalidTokenError" in c["text"] for c in ctx)
    assert any(c["line"] == 9 and "return payload" in c["text"] for c in ctx)

    # 2. Case-sensitive search
    res_cs = service.grep_code(pattern="invalidtokenerror", case_sensitive=True)
    assert res_cs["total_matches"] == 0

    res_cs_exact = service.grep_code(pattern="InvalidTokenError", case_sensitive=True)
    assert res_cs_exact["total_matches"] == 2


def test_grep_code_regex_and_syntax_error(grep_test_env):
    watched_dir = grep_test_env["watched_dir"]
    sub_dir = watched_dir / "app"
    sub_dir.mkdir(parents=True, exist_ok=True)
    f = sub_dir / "config.py"
    f.write_text("TIMEOUT = 300\nRETRY_COUNT = 5\nPORT = 8080\n", encoding="utf-8")

    service = get_file_reader_service()

    # Regex search
    res = service.grep_code(pattern=r"[A-Z_]+\s*=\s*\d+", is_regex=True)
    assert res["total_matches"] == 3

    # Invalid regex syntax
    with pytest.raises(ValueError, match="Invalid regular expression pattern"):
        service.grep_code(pattern="[unclosed(regex", is_regex=True)


def test_grep_code_repo_and_glob_filters(grep_test_env):
    watched_dir = grep_test_env["watched_dir"]
    (watched_dir / "a.py").write_text("target_token = 1\n", encoding="utf-8")
    (watched_dir / "b.txt").write_text("target_token = 2\n", encoding="utf-8")

    service = get_file_reader_service()

    # Matching *.py only
    res_py = service.grep_code(pattern="target_token", path_glob="*.py")
    assert res_py["total_matches"] == 1
    assert res_py["matches"][0]["file"] == "a.py"

    # Matching repo filter that doesn't match
    res_other = service.grep_code(pattern="target_token", repo="other-service")
    assert res_other["total_matches"] == 0


def test_grep_code_vector_store_fallback_and_deduplication(tmp_path, monkeypatch):
    """Verifies grep_code works for ephemeral/vector-backed files and deduplicates overlapping chunks."""
    db_file = tmp_path / "test_grep_dedup.db"
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    engine = get_db_engine(db_url, reset=True)
    init_db(engine=engine)

    mock_store = MagicMock()
    # Matched line appears in two overlapping chunks:
    # Chunk 1 (lines 10-12), Chunk 2 (lines 11-13)
    chunk1 = {
        "repo": "ephemeral-repo",
        "path": "lib/util.py",
        "rel_path": "lib/util.py",
        "start_line": 10,
        "end_line": 12,
        "content": "line 10\nline 11 MATCHED_SYMBOL\nline 12"
    }
    chunk2 = {
        "repo": "ephemeral-repo",
        "path": "lib/util.py",
        "rel_path": "lib/util.py",
        "start_line": 11,
        "end_line": 13,
        "content": "line 11 MATCHED_SYMBOL\nline 12\nline 13"
    }
    mock_store.grep_chunks.return_value = [chunk1, chunk2]

    with patch("app.services.vector_store.get_vector_store", return_value=mock_store):
        service = FileReaderService(storage_root=str(tmp_path))
        res = service.grep_code(pattern="MATCHED_SYMBOL")
        # Should be deduplicated into 1 match for line 11
        assert res["total_matches"] == 1
        assert res["matches"][0]["line"] == 11
        assert res["matches"][0]["file"] == "lib/util.py"
        assert res["matches"][0]["match_text"] == "line 11 MATCHED_SYMBOL"


@pytest.mark.asyncio
async def test_mcp_grep_code_registration_and_execution(grep_test_env):
    watched_dir = grep_test_env["watched_dir"]
    sub_dir = watched_dir / "services"
    sub_dir.mkdir(parents=True, exist_ok=True)
    test_file = sub_dir / "auth.py"
    test_file.write_text("def authenticate(user):\n    pass\n", encoding="utf-8")

    # Confirm grep_code is registered on mcp_server
    tool_names = [t.name for t in mcp_server._tool_manager.list_tools()]
    assert "grep_code" in tool_names

    # Call handle_grep_code
    out_json = await handle_grep_code(pattern="authenticate", repo="auth-service")
    parsed = json.loads(out_json)
    assert parsed["pattern"] == "authenticate"
    assert parsed["total_matches"] == 1
    assert parsed["matches"][0]["file"] == "services/auth.py"
    assert parsed["matches"][0]["line"] == 1


def test_api_search_grep_endpoint(grep_test_env):
    client = grep_test_env["client"]
    watched_dir = grep_test_env["watched_dir"]
    (watched_dir / "api.py").write_text("ROUTE_KEY = 'secret123'\n", encoding="utf-8")

    resp = client.post("/api/search/grep", json={
        "pattern": "ROUTE_KEY",
        "repo": "auth-service",
        "context_lines": 1
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_matches"] == 1
    assert data["matches"][0]["file"] == "api.py"
    assert data["matches"][0]["match_text"] == "ROUTE_KEY = 'secret123'"
