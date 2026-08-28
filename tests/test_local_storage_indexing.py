import os
import pytest
from app.services.local_storage import LocalStorageService
import app.services.database as db_service
import app.services.vector_store as vs_service

@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_local_indexing.db")
    monkeypatch.setenv("CACHE_DB_PATH", test_db)
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", test_db)
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", test_db)
    db_service.init_db()

def test_incremental_indexing_on_save(tmp_path):
    service = LocalStorageService(storage_root=str(tmp_path))
    content = """# Architecture Plan
This document specifies the local vector storage architecture for AI agents.

## Implementation Details
Key functions include save_file and delete_file.
"""
    res = service.save_file("docs/architecture.md", content, repo="local_storage", category="architecture")
    assert res["status"] == "success"
    assert res["chunks_indexed"] > 0

    abs_path = os.path.abspath(tmp_path / "docs" / "architecture.md")
    with db_service.get_db_connection() as conn:
        f_row = conn.execute("SELECT * FROM indexed_files WHERE filepath = ?", (abs_path,)).fetchone()
        assert f_row is not None
        assert f_row["repo"] == "local_storage"

        s_row = conn.execute("SELECT * FROM file_summaries WHERE filepath = ?", (abs_path,)).fetchone()
        assert s_row is not None
        assert s_row["title"] == "architecture.md"

def test_incremental_indexing_code_file(tmp_path):
    service = LocalStorageService(storage_root=str(tmp_path))
    code_content = """class LocalStore:
    def __init__(self):
        pass

    def retrieve(self, key: str) -> str:
        return key
"""
    res = service.save_file("src/store.py", code_content, repo="local_storage")
    assert res["status"] == "success"
    assert res["chunks_indexed"] > 0

    abs_path = os.path.abspath(tmp_path / "src" / "store.py")
    with db_service.get_db_connection() as conn:
        f_row = conn.execute("SELECT * FROM indexed_files WHERE filepath = ?", (abs_path,)).fetchone()
        assert f_row is not None
        assert f_row["doc_type"] == "code"

        sym_rows = conn.execute("SELECT * FROM ast_symbols WHERE filepath = ?", (abs_path,)).fetchall()
        assert len(sym_rows) >= 1

def test_index_file_not_found(tmp_path):
    service = LocalStorageService(storage_root=str(tmp_path))
    with pytest.raises(FileNotFoundError):
        service.index_file("nonexistent.md")

def test_incremental_deletion(tmp_path):
    service = LocalStorageService(storage_root=str(tmp_path))
    service.save_file("temp.md", "# Temporary Document\nContent to delete")
    abs_path = os.path.abspath(tmp_path / "temp.md")
    
    del_res = service.delete_file("temp.md")
    assert del_res["status"] == "success"
    assert not os.path.exists(abs_path)

    with db_service.get_db_connection() as conn:
        f_row = conn.execute("SELECT * FROM indexed_files WHERE filepath = ?", (abs_path,)).fetchone()
        assert f_row is None
        s_row = conn.execute("SELECT * FROM file_summaries WHERE filepath = ?", (abs_path,)).fetchone()
        assert s_row is None
