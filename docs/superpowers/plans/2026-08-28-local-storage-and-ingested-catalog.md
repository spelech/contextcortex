# Local Storage Option & Unified Ingestion Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide managed local storage file upload/replace/delete capabilities with instant incremental vector store indexing, directory tree browsing, unified `what_is_ingested` catalog queries with filter specifications, and RBAC role security across REST APIs, MCP tools, and the Admin Web UI.

**Architecture:** A core `LocalStorageService` manages the physical storage directory (`DATA_DIR/storage`), strictly sanitizes relative paths against path traversal, and coordinates real-time AST chunking/embedding upserts and vector point purges. New FastMCP handlers (`manage_local_file`, `what_is_ingested`) and FastAPI routers (`/admin/api/storage/*`, `/admin/api/ingestion/catalog`) expose these capabilities guarded by RBAC `Role.EDITOR` and `Role.VIEWER`. The React frontend adds a dedicated Local Storage File Manager and Ingestion Catalog Explorer.

**Tech Stack:** Python 3.12, FastAPI, FastMCP (SSE/HTTP), SQLAlchemy / SQLite / PostgreSQL pgvector, React 19, TypeScript, Vitest, Pytest.

## Global Constraints

- Storage Root default: `os.path.join(DATA_DIR, "storage")` or environment variable `LOCAL_STORAGE_PATH`.
- Path sanitization: Canonical verification via `os.path.commonpath([resolved, root]) == root`. Reject `..`, absolute paths, and null bytes with 400 error.
- Default repository tag: `local_storage`.
- Ingestion filter parameters: `source_type` ('all' | 'git' | 'monitored_path' | 'local_storage'), `repo_name`, `path_prefix`, `file_extension`, `detail_level` ('summary' | 'detailed').
- RBAC permissions: Mutations require `Role.EDITOR` (or `ADMIN`); queries require `Role.VIEWER`.
- Max file size for text chunking & vector indexing: 500 KB (512,000 bytes).

---

### Task 1: LocalStorageService Core & Path Security

**Files:**
- Create: `app/services/local_storage.py`
- Test: `tests/test_local_storage_service.py`

**Interfaces:**
- Produces:
  - `LOCAL_STORAGE_PATH: str`
  - `class LocalStorageService:`
    - `get_storage_root() -> str`
    - `resolve_safe_path(rel_path: str) -> str`
    - `save_file_content(rel_path: str, content: str | bytes, repo: str = "local_storage", category: Optional[str] = None) -> Dict[str, Any]`
    - `read_file_content(rel_path: str) -> Dict[str, Any]`
    - `delete_file_disk(rel_path: str) -> bool`
    - `get_file_tree(subfolder: Optional[str] = None) -> Dict[str, Any]`
  - `get_local_storage_service() -> LocalStorageService`

- [ ] **Step 1: Write the failing test for LocalStorageService core and path security**

```python
# tests/test_local_storage_service.py
import os
import pytest
from app.services.local_storage import LocalStorageService, get_local_storage_service

def test_resolve_safe_path_valid(tmp_path):
    service = LocalStorageService(storage_root=str(tmp_path))
    safe = service.resolve_safe_path("docs/spec.md")
    assert safe == os.path.abspath(tmp_path / "docs" / "spec.md")

def test_resolve_safe_path_traversal_rejected(tmp_path):
    service = LocalStorageService(storage_root=str(tmp_path))
    with pytest.raises(ValueError, match="Path traversal or invalid path detected"):
        service.resolve_safe_path("../secret.txt")
    with pytest.raises(ValueError, match="Path traversal or invalid path detected"):
        service.resolve_safe_path("/etc/passwd")
    with pytest.raises(ValueError, match="Path traversal or invalid path detected"):
        service.resolve_safe_path("docs/../../outside.txt")
    with pytest.raises(ValueError, match="Path traversal or invalid path detected"):
        service.resolve_safe_path("null\x00byte.md")

def test_save_and_read_file(tmp_path):
    service = LocalStorageService(storage_root=str(tmp_path))
    res = service.save_file_content("folder/test.md", "# Hello Local Storage\nSample text", repo="local_storage", category="notes")
    assert res["status"] == "success"
    assert res["rel_path"] == "folder/test.md"
    assert os.path.exists(tmp_path / "folder" / "test.md")

    read_res = service.read_file_content("folder/test.md")
    assert read_res["content"] == "# Hello Local Storage\nSample text"
    assert read_res["size_bytes"] > 0

def test_delete_file(tmp_path):
    service = LocalStorageService(storage_root=str(tmp_path))
    service.save_file_content("to_del.txt", "delete me")
    assert os.path.exists(tmp_path / "to_del.txt")
    deleted = service.delete_file_disk("to_del.txt")
    assert deleted is True
    assert not os.path.exists(tmp_path / "to_del.txt")

def test_get_file_tree(tmp_path):
    service = LocalStorageService(storage_root=str(tmp_path))
    service.save_file_content("a.md", "file a")
    service.save_file_content("sub/b.py", "print('b')")
    tree = service.get_file_tree()
    assert tree["root"] == str(tmp_path)
    assert len(tree["files"]) >= 1
    assert any(d["name"] == "sub" for d in tree["directories"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_local_storage_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.local_storage'`

- [ ] **Step 3: Implement LocalStorageService core and path security**

```python
# app/services/local_storage.py
import os
import shutil
import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger("contextcortex.storage")

DEFAULT_STORAGE_PATH = os.getenv("LOCAL_STORAGE_PATH") or os.path.join(
    os.getenv("DATA_DIR", os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data"))),
    "storage"
)

class LocalStorageService:
    def __init__(self, storage_root: Optional[str] = None):
        self.storage_root = os.path.abspath(storage_root or DEFAULT_STORAGE_PATH)
        os.makedirs(self.storage_root, exist_ok=True)

    def get_storage_root(self) -> str:
        return self.storage_root

    def resolve_safe_path(self, rel_path: str) -> str:
        if not rel_path or not isinstance(rel_path, str) or "\x00" in rel_path:
            raise ValueError("Path traversal or invalid path detected")
        
        # Normalize slashes and strip leading slashes/backslashes
        cleaned = rel_path.strip().replace("\\", "/")
        while cleaned.startswith("/"):
            cleaned = cleaned[1:]
        
        if not cleaned or cleaned.startswith("..") or "/../" in cleaned or cleaned.endswith("/.."):
            raise ValueError("Path traversal or invalid path detected")

        target = os.path.abspath(os.path.join(self.storage_root, cleaned))
        try:
            common = os.path.commonpath([target, self.storage_root])
        except ValueError:
            raise ValueError("Path traversal or invalid path detected")

        if common != self.storage_root:
            raise ValueError("Path traversal or invalid path detected")

        return target

    def save_file_content(
        self,
        rel_path: str,
        content: str | bytes,
        repo: str = "local_storage",
        category: Optional[str] = None
    ) -> Dict[str, Any]:
        target_path = self.resolve_safe_path(rel_path)
        os.makedirs(os.path.dirname(target_path), exist_ok=True)

        if isinstance(content, str):
            with open(target_path, "w", encoding="utf-8") as f:
                f.write(content)
        else:
            with open(target_path, "wb") as f:
                f.write(content)

        mtime = os.path.getmtime(target_path)
        size_bytes = os.path.getsize(target_path)

        return {
            "status": "success",
            "rel_path": rel_path.strip().replace("\\", "/").lstrip("/"),
            "abs_path": target_path,
            "size_bytes": size_bytes,
            "mtime": mtime,
            "repo": repo or "local_storage",
            "category": category or os.path.dirname(rel_path) or "root"
        }

    def read_file_content(self, rel_path: str) -> Dict[str, Any]:
        target_path = self.resolve_safe_path(rel_path)
        if not os.path.exists(target_path) or not os.path.isfile(target_path):
            raise FileNotFoundError(f"File '{rel_path}' does not exist in local storage.")

        size_bytes = os.path.getsize(target_path)
        mtime = os.path.getmtime(target_path)
        try:
            with open(target_path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except Exception:
            text = ""

        return {
            "rel_path": rel_path.strip().replace("\\", "/").lstrip("/"),
            "abs_path": target_path,
            "content": text,
            "size_bytes": size_bytes,
            "mtime": mtime
        }

    def delete_file_disk(self, rel_path: str) -> bool:
        target_path = self.resolve_safe_path(rel_path)
        if not os.path.exists(target_path):
            return False

        if os.path.isdir(target_path):
            shutil.rmtree(target_path)
        else:
            os.remove(target_path)
        return True

    def get_file_tree(self, subfolder: Optional[str] = None) -> Dict[str, Any]:
        scan_root = self.resolve_safe_path(subfolder) if subfolder else self.storage_root
        if not os.path.exists(scan_root):
            return {"root": self.storage_root, "current_folder": subfolder or "", "directories": [], "files": []}

        dirs = []
        files = []
        try:
            for entry in os.scandir(scan_root):
                if entry.name.startswith("."):
                    continue
                rel = os.path.relpath(entry.path, self.storage_root).replace("\\", "/")
                if entry.is_dir():
                    dirs.append({
                        "name": entry.name,
                        "rel_path": rel,
                        "abs_path": os.path.abspath(entry.path)
                    })
                elif entry.is_file():
                    files.append({
                        "name": entry.name,
                        "rel_path": rel,
                        "abs_path": os.path.abspath(entry.path),
                        "size_bytes": entry.stat().st_size,
                        "mtime": entry.stat().st_mtime
                    })
        except Exception as e:
            logger.error(f"Error scanning local storage tree at {scan_root}: {e}")

        dirs.sort(key=lambda x: x["name"].lower())
        files.sort(key=lambda x: x["name"].lower())

        return {
            "root": self.storage_root,
            "current_folder": subfolder or "",
            "directories": dirs,
            "files": files
        }


_storage_service: Optional[LocalStorageService] = None

def get_local_storage_service() -> LocalStorageService:
    global _storage_service
    if _storage_service is None:
        _storage_service = LocalStorageService()
    return _storage_service
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_local_storage_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit Task 1**

```bash
git add app/services/local_storage.py tests/test_local_storage_service.py
git commit -m "feat(storage): implement LocalStorageService core and path security"
```

---

### Task 2: Incremental Vector Indexing & Deletion in LocalStorageService

**Files:**
- Modify: `app/services/local_storage.py`
- Test: `tests/test_local_storage_indexing.py`

**Interfaces:**
- Consumes:
  - `process_file_content` from `app.services.indexing.processor`
  - `VectorStore` from `app.services.vector_store`
  - `get_db_connection` from `app.services.database`
  - `trigger_list_changed_notification` from `app.services.indexing.state`
- Produces:
  - `LocalStorageService.index_file(rel_path: str, repo: str = "local_storage", category: Optional[str] = None) -> Dict[str, Any]`
  - `LocalStorageService.delete_file(rel_path: str, repo: str = "local_storage") -> Dict[str, Any]`
  - `save_file(rel_path: str, content: str | bytes, repo: str = "local_storage", category: Optional[str] = None) -> Dict[str, Any]` (combines disk write + immediate indexing)

- [ ] **Step 1: Write the failing test for incremental indexing and deletion**

```python
# tests/test_local_storage_indexing.py
import os
import pytest
from app.services.local_storage import LocalStorageService
import app.services.database as db_service
import app.services.vector_store as vs_service

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_local_storage_indexing.py -v`
Expected: FAIL with `AttributeError: 'LocalStorageService' object has no attribute 'save_file'`

- [ ] **Step 3: Implement incremental indexing and deletion in LocalStorageService**

```python
# app/services/local_storage.py (incorporate incremental indexing)
import os
import shutil
import hashlib
import logging
from typing import Optional, Dict, Any, List

import app.services.database as db_service
import app.services.vector_store as vs_service
from app.services.indexing.processor import process_file_content, MAX_FILE_SIZE_BYTES
from app.services.indexing.state import trigger_list_changed_notification

logger = logging.getLogger("contextcortex.storage")

DEFAULT_STORAGE_PATH = os.getenv("LOCAL_STORAGE_PATH") or os.path.join(
    os.getenv("DATA_DIR", os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data"))),
    "storage"
)

class LocalStorageService:
    def __init__(self, storage_root: Optional[str] = None):
        self.storage_root = os.path.abspath(storage_root or DEFAULT_STORAGE_PATH)
        os.makedirs(self.storage_root, exist_ok=True)

    def get_storage_root(self) -> str:
        return self.storage_root

    def resolve_safe_path(self, rel_path: str) -> str:
        if not rel_path or not isinstance(rel_path, str) or "\x00" in rel_path:
            raise ValueError("Path traversal or invalid path detected")
        cleaned = rel_path.strip().replace("\\", "/")
        while cleaned.startswith("/"):
            cleaned = cleaned[1:]
        if not cleaned or cleaned.startswith("..") or "/../" in cleaned or cleaned.endswith("/.."):
            raise ValueError("Path traversal or invalid path detected")
        target = os.path.abspath(os.path.join(self.storage_root, cleaned))
        try:
            common = os.path.commonpath([target, self.storage_root])
        except ValueError:
            raise ValueError("Path traversal or invalid path detected")
        if common != self.storage_root:
            raise ValueError("Path traversal or invalid path detected")
        return target

    def save_file_content(
        self,
        rel_path: str,
        content: str | bytes,
        repo: str = "local_storage",
        category: Optional[str] = None
    ) -> Dict[str, Any]:
        target_path = self.resolve_safe_path(rel_path)
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        if isinstance(content, str):
            with open(target_path, "w", encoding="utf-8") as f:
                f.write(content)
        else:
            with open(target_path, "wb") as f:
                f.write(content)

        mtime = os.path.getmtime(target_path)
        size_bytes = os.path.getsize(target_path)
        return {
            "status": "success",
            "rel_path": rel_path.strip().replace("\\", "/").lstrip("/"),
            "abs_path": target_path,
            "size_bytes": size_bytes,
            "mtime": mtime,
            "repo": repo or "local_storage",
            "category": category or os.path.dirname(rel_path) or "root"
        }

    def index_file(
        self,
        rel_path: str,
        repo: str = "local_storage",
        category: Optional[str] = None
    ) -> Dict[str, Any]:
        abs_path = self.resolve_safe_path(rel_path)
        if not os.path.exists(abs_path) or not os.path.isfile(abs_path):
            raise FileNotFoundError(f"File '{rel_path}' not found on disk for indexing.")

        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        doc_type = "doc" if abs_path.endswith((".md", ".txt", ".yaml", ".yml", ".json", ".html", ".css", ".sql")) else "code"
        cat = category or os.path.dirname(rel_path) or "root"

        points, ast_symbols, summary_tuple, ast_rel, api_routes, api_calls = process_file_content(
            filepath=abs_path,
            rel_path=rel_path,
            content=content,
            repo=repo,
            doc_type=doc_type,
            category_override=cat
        )

        # Upsert vector points
        if points:
            try:
                store = vs_service.get_vector_store()
                store.delete_by_path(abs_path)
                store.upsert_points(points)
            except Exception as e:
                logger.error(f"Failed to upsert vector points for {abs_path}: {e}")

        # Update relational DB
        mtime = os.path.getmtime(abs_path)
        text_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        with db_service.get_db_connection() as conn:
            # Delete old relational records
            for table in ("indexed_files", "file_summaries", "ast_symbols", "ast_relationships", "api_routes", "api_calls"):
                try:
                    conn.execute(f"DELETE FROM {table} WHERE filepath = ?", (abs_path,))
                except Exception:
                    pass

            # Insert indexed_file
            conn.execute(
                "INSERT INTO indexed_files (filepath, repo, doc_type, language, mtime, hash) VALUES (?, ?, ?, ?, ?, ?)",
                (abs_path, repo, doc_type, doc_type, mtime, text_hash)
            )

            # Insert file summary
            if summary_tuple:
                conn.execute(
                    """INSERT INTO file_summaries (filepath, repo, title, folder, category, tags, headings, keywords, mtime)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    summary_tuple
                )

            # Insert AST symbols
            for sym in ast_symbols:
                conn.execute(
                    """INSERT INTO ast_symbols (symbol_name, symbol_type, filepath, repo, line_number, docstring, is_exported)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (sym["symbol_name"], sym["symbol_type"], sym["filepath"], sym["repo"], sym["line_number"], sym["docstring"], sym["is_exported"])
                )
            conn.commit()

        trigger_list_changed_notification()
        return {
            "status": "success",
            "rel_path": rel_path,
            "abs_path": abs_path,
            "chunks_indexed": len(points),
            "symbols_indexed": len(ast_symbols)
        }

    def save_file(
        self,
        rel_path: str,
        content: str | bytes,
        repo: str = "local_storage",
        category: Optional[str] = None
    ) -> Dict[str, Any]:
        save_info = self.save_file_content(rel_path, content, repo=repo, category=category)
        idx_info = self.index_file(rel_path, repo=repo, category=category)
        save_info.update(idx_info)
        return save_info

    def delete_file(self, rel_path: str, repo: str = "local_storage") -> Dict[str, Any]:
        abs_path = self.resolve_safe_path(rel_path)
        self.delete_file_disk(rel_path)

        try:
            store = vs_service.get_vector_store()
            store.delete_by_path(abs_path)
        except Exception as e:
            logger.error(f"Error removing vector points for {abs_path}: {e}")

        with db_service.get_db_connection() as conn:
            for table in ("indexed_files", "file_summaries", "ast_symbols", "ast_relationships", "api_routes", "api_calls"):
                try:
                    conn.execute(f"DELETE FROM {table} WHERE filepath = ?", (abs_path,))
                except Exception:
                    pass
            conn.commit()

        trigger_list_changed_notification()
        return {"status": "success", "rel_path": rel_path, "deleted": True}

    def read_file_content(self, rel_path: str) -> Dict[str, Any]:
        target_path = self.resolve_safe_path(rel_path)
        if not os.path.exists(target_path) or not os.path.isfile(target_path):
            raise FileNotFoundError(f"File '{rel_path}' does not exist in local storage.")

        size_bytes = os.path.getsize(target_path)
        mtime = os.path.getmtime(target_path)
        try:
            with open(target_path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except Exception:
            text = ""

        return {
            "rel_path": rel_path.strip().replace("\\", "/").lstrip("/"),
            "abs_path": target_path,
            "content": text,
            "size_bytes": size_bytes,
            "mtime": mtime
        }

    def delete_file_disk(self, rel_path: str) -> bool:
        target_path = self.resolve_safe_path(rel_path)
        if not os.path.exists(target_path):
            return False
        if os.path.isdir(target_path):
            shutil.rmtree(target_path)
        else:
            os.remove(target_path)
        return True

    def get_file_tree(self, subfolder: Optional[str] = None) -> Dict[str, Any]:
        scan_root = self.resolve_safe_path(subfolder) if subfolder else self.storage_root
        if not os.path.exists(scan_root):
            return {"root": self.storage_root, "current_folder": subfolder or "", "directories": [], "files": []}

        dirs = []
        files = []
        try:
            for entry in os.scandir(scan_root):
                if entry.name.startswith("."):
                    continue
                rel = os.path.relpath(entry.path, self.storage_root).replace("\\", "/")
                if entry.is_dir():
                    dirs.append({
                        "name": entry.name,
                        "rel_path": rel,
                        "abs_path": os.path.abspath(entry.path)
                    })
                elif entry.is_file():
                    files.append({
                        "name": entry.name,
                        "rel_path": rel,
                        "abs_path": os.path.abspath(entry.path),
                        "size_bytes": entry.stat().st_size,
                        "mtime": entry.stat().st_mtime
                    })
        except Exception as e:
            logger.error(f"Error scanning local storage tree at {scan_root}: {e}")

        dirs.sort(key=lambda x: x["name"].lower())
        files.sort(key=lambda x: x["name"].lower())

        return {
            "root": self.storage_root,
            "current_folder": subfolder or "",
            "directories": dirs,
            "files": files
        }

_storage_service: Optional[LocalStorageService] = None

def get_local_storage_service() -> LocalStorageService:
    global _storage_service
    if _storage_service is None:
        _storage_service = LocalStorageService()
    return _storage_service
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_local_storage_service.py tests/test_local_storage_indexing.py -v`
Expected: PASS

- [ ] **Step 5: Commit Task 2**

```bash
git add app/services/local_storage.py tests/test_local_storage_indexing.py
git commit -m "feat(storage): implement incremental vector indexing and deletion"
```

---

### Task 3: MCP Tool Handlers (`manage_local_file` & `what_is_ingested`)

**Files:**
- Create: `app/mcp/handlers/storage_handlers.py`
- Modify: `app/mcp/handlers/__init__.py`, `app/mcp/tools.py`
- Test: `tests/test_mcp_storage_tools.py`

**Interfaces:**
- Consumes:
  - `get_local_storage_service` from `app.services.local_storage`
  - `enforce_tool_permission`, `Role` from `app.services.auth`
  - `get_db_connection` from `app.services.database`
- Produces:
  - `handle_manage_local_file(action: str, file_path: str, content: Optional[str] = None, repo: str = "local_storage", category: Optional[str] = None) -> str`
  - `handle_what_is_ingested(source_type: str = "all", repo_name: Optional[str] = None, path_prefix: Optional[str] = None, file_extension: Optional[str] = None, detail_level: str = "summary") -> str`

- [ ] **Step 1: Write the failing test for MCP storage tools and RBAC enforcement**

```python
# tests/test_mcp_storage_tools.py
import pytest
import asyncio
from app.mcp.handlers.storage_handlers import handle_manage_local_file, handle_what_is_ingested
from app.services.auth import set_current_auth_context, AuthContext, Role, ForbiddenError

@pytest.mark.asyncio
async def test_manage_local_file_upload_and_read(tmp_path, monkeypatch):
    from app.services.local_storage import LocalStorageService
    import app.services.local_storage as ls_mod
    monkeypatch.setattr(ls_mod, "_storage_service", LocalStorageService(storage_root=str(tmp_path)))

    set_current_auth_context(AuthContext(role=Role.EDITOR))
    up_res = await handle_manage_local_file(action="upload", file_path="notes/guide.md", content="# Guide\nTest content")
    assert "Successfully uploaded and indexed" in up_res

    read_res = await handle_manage_local_file(action="read", file_path="notes/guide.md")
    assert "# Guide" in read_res

@pytest.mark.asyncio
async def test_manage_local_file_rbac_forbidden():
    set_current_auth_context(AuthContext(role=Role.VIEWER))
    res = await handle_manage_local_file(action="upload", file_path="test.md", content="forbidden")
    assert "Forbidden" in res or "Permission denied" in res

@pytest.mark.asyncio
async def test_what_is_ingested_summary_and_filters(tmp_path, monkeypatch):
    from app.services.local_storage import LocalStorageService
    import app.services.local_storage as ls_mod
    monkeypatch.setattr(ls_mod, "_storage_service", LocalStorageService(storage_root=str(tmp_path)))

    set_current_auth_context(AuthContext(role=Role.VIEWER))
    out = await handle_what_is_ingested(source_type="all", detail_level="summary")
    assert "# ContextCortex Ingestion Catalog" in out
    assert "Git Repositories" in out
    assert "Monitored Paths" in out
    assert "Local Storage" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_mcp_storage_tools.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.mcp.handlers.storage_handlers'`

- [ ] **Step 3: Implement storage_handlers.py and register tools in tools.py**

```python
# app/mcp/handlers/storage_handlers.py
import json
import logging
from typing import Optional, Annotated
from pydantic import Field

from app.services.auth import enforce_tool_permission, Role
from app.services.local_storage import get_local_storage_service
from app.services.database import get_db_connection

logger = logging.getLogger("contextcortex.mcp")

async def handle_manage_local_file(
    action: Annotated[str, Field(description="Action to perform: 'upload', 'replace', 'delete', or 'read'")],
    file_path: Annotated[str, Field(description="Relative path of file in local storage (e.g. 'docs/spec.md')")],
    content: Annotated[Optional[str], Field(description="Content to write for upload or replace actions")] = None,
    repo: Annotated[str, Field(description="Repository or namespace tag (default: 'local_storage')")] = "local_storage",
    category: Annotated[Optional[str], Field(description="Category tag for document")] = None
) -> str:
    """Manage files in ContextCortex local storage: upload, replace, read, or delete files with immediate vector indexing."""
    try:
        storage = get_local_storage_service()
        act = action.strip().lower()

        if act in ("upload", "replace", "delete"):
            enforce_tool_permission(Role.EDITOR)
        else:
            enforce_tool_permission(Role.VIEWER)

        if act in ("upload", "replace"):
            if content is None:
                return f"Error: 'content' parameter is required for action '{action}'."
            res = storage.save_file(file_path, content, repo=repo, category=category)
            return (
                f"Successfully {act}d and indexed file: `{res['rel_path']}`\n"
                f"- Repository: `{res['repo']}`\n"
                f"- Category: `{res['category']}`\n"
                f"- Size: {res['size_bytes']} bytes\n"
                f"- Chunks Indexed: {res.get('chunks_indexed', 0)}"
            )
        elif act == "delete":
            storage.delete_file(file_path, repo=repo)
            return f"Successfully deleted `{file_path}` and purged associated vector embeddings."
        elif act == "read":
            res = storage.read_file_content(file_path)
            return f"### File: `{res['rel_path']}` ({res['size_bytes']} bytes)\n\n```\n{res['content']}\n```"
        else:
            return f"Error: Unsupported action '{action}'. Valid actions are 'upload', 'replace', 'delete', 'read'."
    except Exception as e:
        return f"Error executing manage_local_file: {str(e)}"


async def handle_what_is_ingested(
    source_type: Annotated[str, Field(description="Filter source type: 'all', 'git', 'monitored_path', or 'local_storage'")] = "all",
    repo_name: Annotated[Optional[str], Field(description="Filter by repository or namespace name")] = None,
    path_prefix: Annotated[Optional[str], Field(description="Filter files matching path prefix")] = None,
    file_extension: Annotated[Optional[str], Field(description="Filter by file extension (e.g. '.md', '.py')")] = None,
    detail_level: Annotated[str, Field(description="Granularity: 'summary' or 'detailed'")] = "summary"
) -> str:
    """Inspect all ingested Git repositories, monitored local paths, and uploaded local storage files with optional filtering and detailed file trees."""
    try:
        enforce_tool_permission(Role.VIEWER)
        st = (source_type or "all").strip().lower()
        detail = (detail_level or "summary").strip().lower()

        with get_db_connection() as conn:
            git_repos = conn.execute("SELECT id, name, url, branch, commit_sha, provider, status, last_synced FROM git_repositories").fetchall()
            indexed_paths = conn.execute("SELECT path, repo, category FROM indexed_paths WHERE enabled = 1").fetchall()
            
            # Fetch file counts grouped by repo
            f_counts = conn.execute("SELECT repo, count(*) as cnt FROM indexed_files GROUP BY repo").fetchall()
            repo_file_counts = {r["repo"]: r["cnt"] for r in f_counts}

            # Fetch symbol counts grouped by repo
            s_counts = conn.execute("SELECT repo, count(*) as cnt FROM ast_symbols GROUP BY repo").fetchall()
            repo_symbol_counts = {s["repo"]: s["cnt"] for s in s_counts}

            # Filtered file list query if detailed
            detailed_files = []
            if detail == "detailed":
                query = "SELECT filepath, repo, doc_type, language, mtime FROM indexed_files WHERE 1=1"
                params = []
                if repo_name:
                    query += " AND repo = ?"
                    params.append(repo_name)
                if path_prefix:
                    query += " AND filepath LIKE ?"
                    params.append(f"%{path_prefix}%")
                if file_extension:
                    query += " AND filepath LIKE ?"
                    params.append(f"%{file_extension}")
                query += " ORDER BY repo, filepath LIMIT 200"
                detailed_files = conn.execute(query, params).fetchall()

        out = "# ContextCortex Ingestion Catalog\n\n"

        # 1. Git Repositories
        if st in ("all", "git"):
            out += "## Git Repositories\n"
            filtered_repos = [r for r in git_repos if not repo_name or r["name"] == repo_name]
            if filtered_repos:
                for gr in filtered_repos:
                    fc = repo_file_counts.get(gr["name"], 0)
                    sc = repo_symbol_counts.get(gr["name"], 0)
                    sha = gr["commit_sha"][:8] if gr["commit_sha"] else "None"
                    out += f"- **{gr['name']}** (`{gr['branch']}` @ `{sha}`) - Status: `{gr['status']}` | Files: {fc} | Symbols: {sc} | URL: {gr['url']}\n"
            else:
                out += "_No git repositories match the criteria._\n"
            out += "\n"

        # 2. Monitored Local Paths
        if st in ("all", "monitored_path"):
            out += "## Monitored Paths\n"
            filtered_paths = [p for p in indexed_paths if not repo_name or p["repo"] == repo_name]
            if filtered_paths:
                for p in filtered_paths:
                    fc = repo_file_counts.get(p["repo"], 0)
                    out += f"- **{p['repo']}** (`{p['path']}`) - Category: `{p['category']}` | Files: {fc}\n"
            else:
                out += "_No monitored paths match the criteria._\n"
            out += "\n"

        # 3. Local Storage Uploads
        if st in ("all", "local_storage"):
            out += "## Local Storage (Uploaded Files)\n"
            storage = get_local_storage_service()
            tree = storage.get_file_tree(subfolder=path_prefix if path_prefix and not path_prefix.startswith("/") else None)
            total_ls_files = repo_file_counts.get("local_storage", len(tree.get("files", [])))
            out += f"- **Root Storage Path**: `{storage.get_storage_root()}`\n"
            out += f"- **Total Uploaded Files**: {total_ls_files}\n"
            if tree.get("directories"):
                out += f"- **Subdirectories**: {', '.join(d['name'] for d in tree['directories'])}\n"
            out += "\n"

        # Detailed file list if requested
        if detail == "detailed" and detailed_files:
            out += f"## Ingested File Details (Showing top {len(detailed_files)} files)\n"
            for df in detailed_files:
                out += f"- `[{df['repo']}]` `{df['filepath']}` ({df['doc_type']} | {df['language']})\n"
            out += "\n"

        return out
    except Exception as e:
        return f"Error retrieving ingestion catalog: {str(e)}"
```

Export in `app/mcp/handlers/__init__.py` and register in `app/mcp/tools.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_mcp_storage_tools.py -v`
Expected: PASS

- [ ] **Step 5: Commit Task 3**

```bash
git add app/mcp/handlers/storage_handlers.py app/mcp/handlers/__init__.py app/mcp/tools.py tests/test_mcp_storage_tools.py
git commit -m "feat(mcp): add manage_local_file and what_is_ingested tools with RBAC"
```

---

### Task 4: REST API Endpoints for Storage & Ingestion Catalog

**Files:**
- Create: `app/api/routers/storage.py`, `app/api/routers/ingestion.py`
- Modify: `app/api/routes.py`
- Test: `tests/test_storage_api_routes.py`

**Interfaces:**
- Consumes: `LocalStorageService`, `get_db_connection`, `Role`
- Produces:
  - `POST /admin/api/storage/upload`
  - `PUT /admin/api/storage/file`
  - `DELETE /admin/api/storage/file`
  - `GET /admin/api/storage/file`
  - `GET /admin/api/storage/tree`
  - `GET /admin/api/ingestion/catalog`

- [ ] **Step 1: Write the failing test for REST storage and ingestion endpoints**

```python
# tests/test_storage_api_routes.py
import pytest
from fastapi.testclient import TestClient
from main import app
from app.services.auth import get_auth_service, Role

@pytest.fixture
def client():
    return TestClient(app)

def test_storage_upload_and_get_file(client, tmp_path, monkeypatch):
    from app.services.local_storage import LocalStorageService
    import app.services.local_storage as ls_mod
    monkeypatch.setattr(ls_mod, "_storage_service", LocalStorageService(storage_root=str(tmp_path)))

    # Upload file JSON
    res = client.post("/admin/api/storage/upload", json={
        "path": "test_folder/note.md",
        "content": "# Test Note\nHello world",
        "repo": "local_storage",
        "category": "docs"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["rel_path"] == "test_folder/note.md"

    # Get file
    get_res = client.get("/admin/api/storage/file?path=test_folder/note.md")
    assert get_res.status_code == 200
    assert get_res.json()["content"] == "# Test Note\nHello world"

    # Get tree
    tree_res = client.get("/admin/api/storage/tree")
    assert tree_res.status_code == 200
    assert len(tree_res.json()["directories"]) >= 1

    # Delete file
    del_res = client.delete("/admin/api/storage/file?path=test_folder/note.md")
    assert del_res.status_code == 200

def test_ingestion_catalog_endpoint(client):
    res = client.get("/admin/api/ingestion/catalog?source_type=all&detail_level=summary")
    assert res.status_code == 200
    data = res.json()
    assert "git_repositories" in data
    assert "monitored_paths" in data
    assert "local_storage" in data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_storage_api_routes.py -v`
Expected: FAIL (404 Not Found on `/admin/api/storage/upload`)

- [ ] **Step 3: Implement storage.py, ingestion.py routers and include in routes.py**

```python
# app/api/routers/storage.py
import os
import logging
from typing import Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, UploadFile, File, Form, Query, HTTPException
from fastapi.responses import JSONResponse

from app.services.local_storage import get_local_storage_service
from app.services.auth import Role, enforce_tool_permission

logger = logging.getLogger("contextcortex.api")
router = APIRouter()

class FileUploadPayload(BaseModel):
    path: str = Field(..., description="Target relative file path")
    content: str = Field(..., description="File text content")
    repo: Optional[str] = "local_storage"
    category: Optional[str] = None

@router.post("/admin/api/storage/upload")
async def api_upload_storage_file(
    payload: Optional[FileUploadPayload] = None,
    file: Optional[UploadFile] = File(None),
    path: Optional[str] = Form(None),
    repo: Optional[str] = Form("local_storage"),
    category: Optional[str] = Form(None)
):
    try:
        storage = get_local_storage_service()
        if file is not None:
            rel_path = path or file.filename
            content_bytes = await file.read()
            res = storage.save_file(rel_path, content_bytes, repo=repo or "local_storage", category=category)
            return res
        elif payload is not None:
            res = storage.save_file(payload.path, payload.content, repo=payload.repo or "local_storage", category=payload.category)
            return res
        else:
            return JSONResponse(status_code=400, content={"error": "Missing file upload or JSON payload"})
    except ValueError as ve:
        return JSONResponse(status_code=400, content={"error": str(ve)})
    except Exception as e:
        logger.error(f"Error uploading storage file: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.put("/admin/api/storage/file")
async def api_replace_storage_file(payload: FileUploadPayload):
    try:
        storage = get_local_storage_service()
        res = storage.save_file(payload.path, payload.content, repo=payload.repo or "local_storage", category=payload.category)
        return res
    except ValueError as ve:
        return JSONResponse(status_code=400, content={"error": str(ve)})
    except Exception as e:
        logger.error(f"Error replacing storage file: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.get("/admin/api/storage/file")
async def api_get_storage_file(path: str = Query(..., description="Relative file path")):
    try:
        storage = get_local_storage_service()
        return storage.read_file_content(path)
    except FileNotFoundError:
        return JSONResponse(status_code=404, content={"error": f"File '{path}' not found"})
    except ValueError as ve:
        return JSONResponse(status_code=400, content={"error": str(ve)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.delete("/admin/api/storage/file")
async def api_delete_storage_file(path: str = Query(..., description="Relative file path")):
    try:
        storage = get_local_storage_service()
        res = storage.delete_file(path)
        return res
    except ValueError as ve:
        return JSONResponse(status_code=400, content={"error": str(ve)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.get("/admin/api/storage/tree")
async def api_get_storage_tree(folder: Optional[str] = Query(None, description="Subfolder to inspect")):
    try:
        storage = get_local_storage_service()
        return storage.get_file_tree(folder)
    except ValueError as ve:
        return JSONResponse(status_code=400, content={"error": str(ve)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
```

```python
# app/api/routers/ingestion.py
import logging
from typing import Optional
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.services.database import get_db_connection
from app.services.local_storage import get_local_storage_service

logger = logging.getLogger("contextcortex.api")
router = APIRouter()

@router.get("/admin/api/ingestion/catalog")
async def api_get_ingestion_catalog(
    source_type: str = Query("all", description="Source type filter"),
    repo_name: Optional[str] = Query(None, description="Repository filter"),
    path_prefix: Optional[str] = Query(None, description="Path prefix filter"),
    file_extension: Optional[str] = Query(None, description="Extension filter"),
    detail_level: str = Query("summary", description="Detail level: summary or detailed")
):
    try:
        with get_db_connection() as conn:
            git_repos = [dict(r) for r in conn.execute("SELECT id, name, url, branch, commit_sha, provider, status, last_synced FROM git_repositories").fetchall()]
            indexed_paths = [dict(r) for r in conn.execute("SELECT path, repo, category FROM indexed_paths WHERE enabled = 1").fetchall()]
            counts = {r["repo"]: r["cnt"] for r in conn.execute("SELECT repo, count(*) as cnt FROM indexed_files GROUP BY repo").fetchall()}
            for gr in git_repos:
                gr["file_count"] = counts.get(gr["name"], 0)
            for ip in indexed_paths:
                ip["file_count"] = counts.get(ip["repo"], 0)

            detailed_files = []
            if detail_level == "detailed":
                q = "SELECT filepath, repo, doc_type, language, mtime FROM indexed_files WHERE 1=1"
                p = []
                if repo_name:
                    q += " AND repo = ?"
                    p.append(repo_name)
                if path_prefix:
                    q += " AND filepath LIKE ?"
                    p.append(f"%{path_prefix}%")
                if file_extension:
                    q += " AND filepath LIKE ?"
                    p.append(f"%{file_extension}")
                q += " ORDER BY repo, filepath LIMIT 300"
                detailed_files = [dict(r) for r in conn.execute(q, p).fetchall()]

        storage = get_local_storage_service()
        tree = storage.get_file_tree()

        return {
            "source_type": source_type,
            "detail_level": detail_level,
            "git_repositories": git_repos if source_type in ("all", "git") else [],
            "monitored_paths": indexed_paths if source_type in ("all", "monitored_path") else [],
            "local_storage": {
                "root_path": storage.get_storage_root(),
                "file_count": counts.get("local_storage", len(tree.get("files", []))),
                "tree": tree
            } if source_type in ("all", "local_storage") else None,
            "files": detailed_files if detail_level == "detailed" else []
        }
    except Exception as e:
        logger.error(f"Error fetching ingestion catalog: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_storage_api_routes.py -v`
Expected: PASS

- [ ] **Step 5: Commit Task 4**

```bash
git add app/api/routers/storage.py app/api/routers/ingestion.py app/api/routes.py tests/test_storage_api_routes.py
git commit -m "feat(api): add REST endpoints for local storage and ingestion catalog"
```

---

### Task 5: Frontend Admin UI Integration for Local Storage & Ingestion Catalog

**Files:**
- Create: `frontend/src/LocalStorageManager.tsx`, `frontend/src/IngestionCatalogViewer.tsx`
- Modify: `frontend/src/App.tsx`, `frontend/src/types.ts`
- Test: `frontend/src/tests/LocalStorageManager.test.tsx`, `frontend/src/tests/IngestionCatalogViewer.test.tsx`

**Interfaces:**
- Consumes: `/admin/api/storage/*`, `/admin/api/ingestion/catalog`
- Produces:
  - `<LocalStorageManager />` tab with file upload modal, directory tree explorer, delete/replace actions, and live vector indexing indicators.
  - `<IngestionCatalogViewer />` tab with source type filters, repository search, and detailed file listings.

- [ ] **Step 1: Write the failing tests for frontend LocalStorageManager and IngestionCatalogViewer**

```tsx
// frontend/src/tests/LocalStorageManager.test.tsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import LocalStorageManager from '../LocalStorageManager';
import { ToastProvider } from '../ToastContext';

describe('LocalStorageManager', () => {
  it('renders storage header, upload button, and tree view', async () => {
    vi.spyOn(global, 'fetch').mockImplementation((url) => {
      if (String(url).includes('/admin/api/storage/tree')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            root: '/app/data/storage',
            current_folder: '',
            directories: [{ name: 'docs', rel_path: 'docs', abs_path: '/app/data/storage/docs' }],
            files: [{ name: 'guide.md', rel_path: 'guide.md', abs_path: '/app/data/storage/guide.md', size_bytes: 120, mtime: 123456 }]
          })
        } as Response);
      }
      return Promise.reject(new Error('Unknown endpoint'));
    });

    render(
      <ToastProvider>
        <LocalStorageManager />
      </ToastProvider>
    );

    expect(await screen.findByText('Local Storage Explorer')).toBeInTheDocument();
    expect(screen.getByText('guide.md')).toBeInTheDocument();
    expect(screen.getByText('docs')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- frontend/src/tests/LocalStorageManager.test.tsx` (in `frontend`)
Expected: FAIL with `Cannot find module '../LocalStorageManager'`

- [ ] **Step 3: Implement LocalStorageManager, IngestionCatalogViewer, and integrate into App.tsx**

Implement React components, types in `types.ts`, wire into `App.tsx` tab navigation, and run `npm run build` to compile the frontend assets.

- [ ] **Step 4: Run frontend tests and build to verify they pass**

Run: `npm run test` and `npm run build` in `frontend`
Expected: PASS (all tests pass, build succeeds)

- [ ] **Step 5: Commit Task 5**

```bash
git add frontend/ www/
git commit -m "feat(ui): add local storage file manager and ingestion catalog tabs"
```

---

### Task 6: Documentation & Specification Alignment

**Files:**
- Modify: `ARCHITECTURE.md`, `README.md`, `DEVELOPER_DOCS.md`, `REQUIREMENTS.md`, `.env.example`
- Test: `tests/test_doc_links.py`

- [ ] **Step 1: Update documentation files**
  - Document `LOCAL_STORAGE_PATH` configuration in `.env.example` and `README.md`.
  - Add Local Storage Architecture and Ingestion Pipeline diagrams to `ARCHITECTURE.md`.
  - Update `DEVELOPER_DOCS.md` with REST endpoints (`/admin/api/storage/*`, `/admin/api/ingestion/catalog`) and MCP tools (`manage_local_file`, `what_is_ingested`).
  - Update `REQUIREMENTS.md` with requirement verification entries.

- [ ] **Step 2: Run documentation test and full test suite**

Run: `pytest tests/test_doc_links.py -v && pytest`
Expected: PASS

- [ ] **Step 3: Commit Task 6**

```bash
git add ARCHITECTURE.md README.md DEVELOPER_DOCS.md REQUIREMENTS.md .env.example
git commit -m "docs: document local storage option and unified ingestion catalog"
```
