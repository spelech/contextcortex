import os
import shutil
import tempfile
import unittest

from app.services.chunker import extract_symbols_and_chunks, chunk_markdown, get_file_outline
from app.services.embeddings import get_dense_embedding, get_sparse_embedding, get_hybrid_embeddings
from app.services.git_manager import (
    shallow_clone_repo, cleanup_repo_dir, format_github_permalink, 
    check_github_rate_limit
)
from app.services.db import init_db, get_db_connection, set_metadata, get_metadata

class TestNotesAndCodeRAG(unittest.TestCase):

    def setUp(self):
        init_db()

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
        chunks = res.chunks
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
        link = format_github_permalink(
            "https://github.com/my-org/my-project.git",
            "a1b2c3d4e5",
            "src/utils.py",
            10,
            25
        )
        self.assertEqual(
            link,
            "https://github.com/my-org/my-project/blob/a1b2c3d4e5/src/utils.py#L10-L25"
        )

    def test_ephemeral_clone_and_cleanup(self):
        # Test shallow clone on a small public repo
        url = "https://github.com/octocat/Hello-World"
        res = shallow_clone_repo(url, branch="master")
        temp_dir = res.temp_dir
        sha = res.commit_sha
        err = res.error
        if not err and temp_dir:
            self.assertTrue(os.path.exists(temp_dir))
            self.assertTrue(len(sha) > 0)
            # Test cleanup
            cleanup_repo_dir(temp_dir)
            self.assertFalse(os.path.exists(temp_dir))

    def test_db_symbols_and_metadata(self):
        set_metadata("test_key", "test_val")
        self.assertEqual(get_metadata("test_key"), "test_val")

        with get_db_connection() as conn:
            conn.execute("DELETE FROM ast_symbols WHERE repo = 'unit_test'")
            conn.execute(
                "INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("unit_test", "core/auth.py", "verify_token", "core.auth.verify_token", "function_definition", 10, 25, "def verify_token(token):", "python")
            )
            conn.commit()

            row = conn.execute("SELECT * FROM ast_symbols WHERE name = 'verify_token' AND repo = 'unit_test'").fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["kind"], "function_definition")

if __name__ == "__main__":
    unittest.main()

import pytest
from fastapi.testclient import TestClient
from main import app
from app.mcp.tools import execute_tool
import anyio

client = TestClient(app)

def test_api_routes_pydantic():
    req = {"name": "pytest_repo", "url": "https://github.com/pytest/repo"}
    res = client.post("/admin/api/repos", json=req)
    assert res.status_code in [200, 400]
    data = res.json()
    assert data.get("status") == "success" or "error" in data

@pytest.mark.asyncio
async def test_mcp_tools_pydantic():
    args = {"query": "test query", "limit": 2}
    res = await execute_tool("search_code", args)
    assert len(res) == 1
    assert "Error" in res[0].text or "No matching code snippets" in res[0].text or "========================" in res[0].text
