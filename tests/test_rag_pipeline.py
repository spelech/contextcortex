import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import app.services.database as db_mod
import app.services.database.connection as conn_mod
from app.mcp.tools import handle_search
from app.services.chunking import chunk_markdown, extract_symbols_and_chunks
from app.services.database import (
    get_db_connection,
    get_db_engine,
    get_metadata,
    init_db,
    set_metadata,
)
from app.services.embeddings import get_hybrid_embeddings
from app.services.git_manager import (
    cleanup_repo_dir,
    format_git_permalink,
    shallow_clone_repo,
)
from main import app

client = TestClient(app)


class TestKnowledgeRAG(unittest.TestCase):

    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self._db_path = os.path.join(self._tmp_dir.name, "test_rag_pipeline.db")
        self._prev_cache_env = os.environ.get("CACHE_DB_PATH")
        self._prev_db_url_env = os.environ.get("DATABASE_URL")
        self._prev_db_mod_path = getattr(db_mod, "CACHE_DB_PATH", None)
        self._prev_conn_mod_path = getattr(conn_mod, "CACHE_DB_PATH", None)

        os.environ["CACHE_DB_PATH"] = self._db_path
        os.environ["DATABASE_URL"] = f"sqlite:///{self._db_path}"
        db_mod.CACHE_DB_PATH = self._db_path
        conn_mod.CACHE_DB_PATH = self._db_path

        engine = get_db_engine(f"sqlite:///{self._db_path}", reset=True)
        init_db(engine=engine)

    def tearDown(self):
        if self._prev_cache_env is None:
            os.environ.pop("CACHE_DB_PATH", None)
        else:
            os.environ["CACHE_DB_PATH"] = self._prev_cache_env

        if self._prev_db_url_env is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = self._prev_db_url_env

        if self._prev_db_mod_path is not None:
            db_mod.CACHE_DB_PATH = self._prev_db_mod_path
        if self._prev_conn_mod_path is not None:
            conn_mod.CACHE_DB_PATH = self._prev_conn_mod_path

        get_db_engine(reset=True)
        self._tmp_dir.cleanup()

    def test_tree_sitter_python_ast(self):
        sample_code = """
class DataProcessor:
    def __init__(self, config: dict):
        self.config = config

    def process_records(self, items: list) -> int:
        \"\"\"Process a list of data records.\"\"\"
        count = 0
        for item in items:
            count += 1
        return count

def standalone_helper(x: int) -> int:
    return x * 2
"""
        res = extract_symbols_and_chunks(sample_code, "src/processor.py", repo="test_repo")
        symbols = res.symbols
        outline = res.outline

        symbol_names = [s.name for s in symbols]
        self.assertIn("DataProcessor", symbol_names)
        self.assertIn("__init__", symbol_names)
        self.assertIn("process_records", symbol_names)
        self.assertIn("standalone_helper", symbol_names)

        # Verify start/end line numbers
        proc_sym = next(s for s in symbols if s.name == "process_records")
        self.assertEqual(proc_sym.start_line, 6)

        # Check outline
        self.assertTrue(len(outline) >= 4)

    def test_markdown_chunking(self):
        sample_md = """# Architecture Overview
This is the intro section.

## Database Schema
The database uses SQLite and Qdrant.

## API Endpoints
- GET /admin/api/stats
- POST /admin/api/repos
"""
        chunks = chunk_markdown(sample_md)
        headings = [c.heading for c in chunks]
        self.assertIn("Architecture Overview", headings)
        self.assertIn("Database Schema", headings)
        self.assertIn("API Endpoints", headings)

    def test_hybrid_embeddings(self):
        text = "def authenticate_jwt_token(token: str): pass"
        hybrid = get_hybrid_embeddings(text)
        self.assertIn("dense", hybrid)
        self.assertEqual(len(hybrid["dense"]), 384)
        if "sparse" in hybrid:
            self.assertTrue(len(hybrid["sparse"].indices) > 0)
            self.assertTrue(len(hybrid["sparse"].values) > 0)

    def test_github_permalink(self):
        link = format_git_permalink(
            "https://github.com/my-org/my-project.git",
            "a1b2c3d4e5",
            "src/utils.py",
            10,
            25,
        )
        self.assertEqual(
            link,
            "https://github.com/my-org/my-project/blob/a1b2c3d4e5/src/utils.py#L10-L25",
        )

    def test_ephemeral_clone_and_cleanup(self):
        origin_dir = os.path.join(self._tmp_dir.name, "origin_repo")
        os.makedirs(origin_dir, exist_ok=True)
        subprocess.run(["git", "init", origin_dir], check=True, capture_output=True, text=True)
        subprocess.run(["git", "-C", origin_dir, "checkout", "-b", "master"], check=True, capture_output=True, text=True)
        subprocess.run(["git", "-C", origin_dir, "config", "user.email", "test@contextcortex.local"], check=True, capture_output=True, text=True)
        subprocess.run(["git", "-C", origin_dir, "config", "user.name", "Test Runner"], check=True, capture_output=True, text=True)

        readme_path = os.path.join(origin_dir, "README.md")
        with open(readme_path, "w", encoding="utf-8") as f:
            f.write("# Local Test Repo\n")

        subprocess.run(["git", "-C", origin_dir, "add", "README.md"], check=True, capture_output=True, text=True)
        subprocess.run(["git", "-C", origin_dir, "commit", "-m", "Initial local commit"], check=True, capture_output=True, text=True)

        url = f"file://{origin_dir}"
        res = shallow_clone_repo(url, branch="master")
        self.assertIsNone(res.error)
        self.assertIsNotNone(res.temp_dir)
        self.assertTrue(os.path.exists(res.temp_dir))
        self.assertTrue(len(res.commit_sha) > 0)

        cleanup_repo_dir(res.temp_dir)
        self.assertFalse(os.path.exists(res.temp_dir))

    def test_db_symbols_and_metadata(self):
        set_metadata("test_key", "test_val")
        self.assertEqual(get_metadata("test_key"), "test_val")

        with get_db_connection() as conn:
            conn.execute("DELETE FROM ast_symbols WHERE repo = 'unit_test'")
            conn.execute(
                "INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("unit_test", "core/auth.py", "verify_token", "core.auth.verify_token", "function_definition", 10, 25, "def verify_token(token):", "python"),
            )
            conn.commit()

            row = conn.execute("SELECT * FROM ast_symbols WHERE name = 'verify_token' AND repo = 'unit_test'").fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["kind"], "function_definition")


def test_api_routes_pydantic():
    req = {"name": "pytest_repo", "url": "https://github.com/pytest/repo"}
    with patch("app.services.indexing.sync_single_git_repo"):
        res = client.post("/admin/api/repos", json=req)
    assert res.status_code in [200, 400]
    data = res.json()
    assert data.get("status") == "success" or "error" in data


@pytest.mark.asyncio
async def test_mcp_tools_pydantic():
    res = await handle_search(query="test query", scope="code", limit=2)
    assert isinstance(res, str)
    data = json.loads(res)
    assert "results" in data or "error" in data


if __name__ == "__main__":
    unittest.main()
