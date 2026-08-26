# Incremental Ingestion, Chunk Embedding Cache & Doc Graph Linking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement true incremental git repository syncing, chunk content-hash embedding caching, and documentation graph linking to eliminate recurring ingestion latency and token costs for large repositories.

**Architecture:** Detect file diffs (Added, Modified, Deleted, Unchanged) via SHA256 content hashes in SQLite `indexed_files`; persist a chunk-level SHA256 `embedding_cache` in SQLite to reuse vectors across commits and branch switches; extract markdown relative links and Obsidian wikilinks into `ast_relationships` (`DOC_LINKS_TO`) to link doc nodes in the topology graph.

**Tech Stack:** Python 3.10+, SQLite3 (WAL mode), FastEmbed / OpenAI LiteLLM, Qdrant / ChromaDB vector stores, Tree-sitter AST, Pytest.

## Global Constraints

- Preserve all existing public API and MCP tool signatures (`search_code`, `search_docs`, `get_architecture`, `find_symbol`, `list_repositories`, `sync_repository`).
- Maintain strict sub-500 LOC per file modular maintainability limit.
- All database operations must use WAL mode SQLite transactions with parameter binding.
- Do not introduce breaking schema changes to existing tables without automatic migration in `init_db()`.
- Ensure all tests pass cleanly under `pytest`.

---

### Task 1: Database Migration & Embedding Cache Layer

**Files:**
- Create: `app/services/database/embedding_cache.py`
- Modify: `app/services/database/connection.py:100-140`
- Modify: `app/services/database/__init__.py:1-30`
- Test: `tests/test_embedding_cache.py`

**Interfaces:**
- Consumes: `app.services.database.connection.get_db_connection`
- Produces:
  - `get_cached_embeddings_batch(chunk_hashes: List[str], model_name: str) -> Dict[str, Dict[str, Any]]`
  - `set_cached_embeddings_batch(items: List[Dict[str, Any]]) -> None`
  - `invalidate_cache_by_model(model_name: Optional[str] = None) -> int`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_embedding_cache.py
import pytest
from app.services.database.connection import init_db, get_db_connection
from app.services.database.embedding_cache import (
    get_cached_embeddings_batch,
    set_cached_embeddings_batch,
    invalidate_cache_by_model
)

@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_cache.db")
    monkeypatch.setenv("CACHE_DB_PATH", test_db)
    init_db()

def test_embedding_cache_set_and_get():
    items = [
        {
            "chunk_hash": "hash_abc_1",
            "dense_vector": [0.1, 0.2, 0.3],
            "sparse_indices": [10, 20],
            "sparse_values": [0.5, 0.8],
            "model_name": "BAAI/bge-small-en-v1.5"
        },
        {
            "chunk_hash": "hash_abc_2",
            "dense_vector": [0.4, 0.5, 0.6],
            "sparse_indices": None,
            "sparse_values": None,
            "model_name": "BAAI/bge-small-en-v1.5"
        }
    ]
    set_cached_embeddings_batch(items)

    res = get_cached_embeddings_batch(["hash_abc_1", "hash_abc_2", "missing_hash"], model_name="BAAI/bge-small-en-v1.5")
    assert "hash_abc_1" in res
    assert "hash_abc_2" in res
    assert "missing_hash" not in res
    assert res["hash_abc_1"]["dense"] == [0.1, 0.2, 0.3]
    assert res["hash_abc_1"]["sparse_indices"] == [10, 20]
    assert res["hash_abc_2"]["dense"] == [0.4, 0.5, 0.6]
    assert res["hash_abc_2"]["sparse_indices"] is None

def test_embedding_cache_model_isolation():
    items = [
        {
            "chunk_hash": "hash_model_test",
            "dense_vector": [0.1, 0.2],
            "sparse_indices": None,
            "sparse_values": None,
            "model_name": "model_a"
        }
    ]
    set_cached_embeddings_batch(items)
    assert "hash_model_test" in get_cached_embeddings_batch(["hash_model_test"], model_name="model_a")
    assert "hash_model_test" not in get_cached_embeddings_batch(["hash_model_test"], model_name="model_b")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_embedding_cache.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.database.embedding_cache'`

- [ ] **Step 3: Implement database schema and embedding cache functions**

Create `app/services/database/embedding_cache.py`:
```python
import json
import logging
from typing import List, Dict, Any, Optional
from app.services.database.connection import get_db_connection

logger = logging.getLogger("contextcortex.db.embedding_cache")

def get_cached_embeddings_batch(chunk_hashes: List[str], model_name: str) -> Dict[str, Dict[str, Any]]:
    if not chunk_hashes:
        return {}
    results = {}
    placeholders = ",".join("?" for _ in chunk_hashes)
    with get_db_connection() as conn:
        rows = conn.execute(
            f"SELECT chunk_hash, dense_vector, sparse_indices, sparse_values FROM embedding_cache WHERE model_name = ? AND chunk_hash IN ({placeholders})",
            [model_name] + list(chunk_hashes)
        ).fetchall()
        for r in rows:
            try:
                dense = json.loads(r["dense_vector"]) if r["dense_vector"] else None
                s_indices = json.loads(r["sparse_indices"]) if r["sparse_indices"] else None
                s_values = json.loads(r["sparse_values"]) if r["sparse_values"] else None
                results[r["chunk_hash"]] = {
                    "dense": dense,
                    "sparse_indices": s_indices,
                    "sparse_values": s_values
                }
            except Exception as e:
                logger.warning(f"Error decoding cached embedding for hash {r['chunk_hash']}: {e}")
    return results

def set_cached_embeddings_batch(items: List[Dict[str, Any]]) -> None:
    if not items:
        return
    rows_to_insert = []
    for item in items:
        dense_json = json.dumps(item["dense_vector"]) if item.get("dense_vector") is not None else None
        sparse_indices_json = json.dumps(item["sparse_indices"]) if item.get("sparse_indices") is not None else None
        sparse_values_json = json.dumps(item["sparse_values"]) if item.get("sparse_values") is not None else None
        model = item.get("model_name", "BAAI/bge-small-en-v1.5")
        rows_to_insert.append((
            item["chunk_hash"],
            dense_json,
            sparse_indices_json,
            sparse_values_json,
            model
        ))
    with get_db_connection() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO embedding_cache (chunk_hash, dense_vector, sparse_indices, sparse_values, model_name)
               VALUES (?, ?, ?, ?, ?)""",
            rows_to_insert
        )
        conn.commit()

def invalidate_cache_by_model(model_name: Optional[str] = None) -> int:
    with get_db_connection() as conn:
        if model_name:
            cur = conn.execute("DELETE FROM embedding_cache WHERE model_name = ?", (model_name,))
        else:
            cur = conn.execute("DELETE FROM embedding_cache")
        conn.commit()
        return cur.rowcount
```

Update `init_db()` in `app/services/database/connection.py` to create `embedding_cache` table and indexes, and export functions in `app/services/database/__init__.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_embedding_cache.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/database/embedding_cache.py app/services/database/connection.py app/services/database/__init__.py tests/test_embedding_cache.py
git commit -m "feat(db): add chunk hash embedding cache layer and schema migration"
```

---

### Task 2: Markdown & Wikilink Extraction for Documentation Graphs

**Files:**
- Modify: `app/services/chunking/text_chunker.py`
- Modify: `app/services/indexing/processor.py:112-150`
- Modify: `app/services/topology/graph_builder.py:229-270`
- Test: `tests/test_doc_links.py`

**Interfaces:**
- Consumes: `extract_markdown_doc_links(content: str, filepath: str, repo: str) -> List[CodeRelationship]`
- Produces: `DOC_LINKS_TO` relationships in `ast_relationships` and `graph_builder.py` edges

- [ ] **Step 1: Write the failing test**

```python
# tests/test_doc_links.py
import pytest
from app.services.chunking.text_chunker import extract_markdown_doc_links
from app.services.indexing.processor import process_file_content
from app.services.topology.graph_builder import get_topology_graph
from app.services.database.connection import init_db, get_db_connection

def test_extract_markdown_doc_links():
    md = """# Title
See [Architecture Spec](../arch/system.md) for details.
Also refer to [[Database Design]] and [[API Routes|Routing Guide]].
External [Google](https://google.com) should be ignored.
"""
    rels = extract_markdown_doc_links(md, filepath="docs/intro.md", repo="test-repo")
    target_names = [r.target_symbol for r in rels]
    assert "arch/system.md" in target_names or "../arch/system.md" in target_names
    assert "Database Design" in target_names
    assert "API Routes" in target_names
    assert all(r.relationship_type == "DOC_LINKS_TO" for r in rels)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_doc_links.py -v`
Expected: FAIL with `ImportError: cannot import name 'extract_markdown_doc_links'`

- [ ] **Step 3: Implement link extractor and graph builder integration**

In `app/services/chunking/text_chunker.py`:
Implement `extract_markdown_doc_links(content: str, filepath: str, repo: str) -> List[CodeRelationship]`.
In `app/services/indexing/processor.py`:
Call `extract_markdown_doc_links` in `process_file_content` when `doc_type == "doc"` and include them in returned `rels`.
In `app/services/topology/graph_builder.py`:
Handle `rel_type == "DOC_LINKS_TO"` to create graph edges between documentation files.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_doc_links.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/chunking/text_chunker.py app/services/indexing/processor.py app/services/topology/graph_builder.py tests/test_doc_links.py
git commit -m "feat(topology): add markdown and wikilink extraction for doc graphs"
```

---

### Task 3: Batch Embedder with Hash Cache Integration

**Files:**
- Modify: `app/services/indexing/processor.py`
- Modify: `app/services/embeddings.py`
- Test: `tests/test_processor_caching.py`

**Interfaces:**
- Consumes: `embedding_cache.get_cached_embeddings_batch`, `embedding_cache.set_cached_embeddings_batch`
- Produces: `process_file_content` with chunk hash deduplication and bulk cache lookup

- [ ] **Step 1: Write the failing test**

```python
# tests/test_processor_caching.py
import pytest
from app.services.indexing.processor import process_file_content, compute_text_hash
from app.services.database.connection import init_db
from app.services.database.embedding_cache import get_cached_embeddings_batch

@pytest.fixture(autouse=True)
def setup_db(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_proc.db")
    monkeypatch.setenv("CACHE_DB_PATH", test_db)
    init_db()

def test_process_file_content_populates_embedding_cache():
    code = "def hello():\n    return 'world'\n"
    points, symbols, summary, rels, routes, calls = process_file_content(
        filepath="test_repo://hello.py",
        rel_path="hello.py",
        content=code,
        repo="test_repo",
        doc_type="code"
    )
    assert len(points) > 0
    # Verify vector is generated
    assert points[0].dense_vector is not None
    # Compute chunk hash and check cache
    chunk_hash = compute_text_hash(points[0].text)
    cached = get_cached_embeddings_batch([chunk_hash], model_name="BAAI/bge-small-en-v1.5")
    assert chunk_hash in cached
    assert cached[chunk_hash]["dense"] == points[0].dense_vector
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_processor_caching.py -v`
Expected: FAIL with `ImportError: cannot import name 'compute_text_hash'`

- [ ] **Step 3: Implement chunk hash caching and batch embedding**

In `app/services/indexing/processor.py`:
- Add `compute_text_hash(text: str) -> str` using `hashlib.sha256(text.encode('utf-8')).hexdigest()`.
- Update `process_file_content` to check `get_cached_embeddings_batch` for all chunk hashes before generating embeddings.
- Only invoke `get_hybrid_embeddings_batch` for missing chunk hashes, and persist new vectors using `set_cached_embeddings_batch`.
- Add file size guard (>500KB) to skip binary/huge lockfiles.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_processor_caching.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/indexing/processor.py app/services/embeddings.py tests/test_processor_caching.py
git commit -m "feat(indexing): integrate chunk-level SHA256 embedding caching and bulk vector retrieval"
```

---

### Task 4: Incremental Git Syncer with Delta Detection

**Files:**
- Modify: `app/services/indexing/git_syncer.py`
- Test: `tests/test_git_incremental.py`

**Interfaces:**
- Consumes: `compute_git_repo_delta(cloned_dir, repo_name) -> (added, modified, deleted, unchanged)`
- Produces: Scoped incremental sync in `sync_single_git_repo`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_git_incremental.py
import os
import pytest
from app.services.database.connection import init_db, get_db_connection
from app.services.indexing.git_syncer import compute_git_repo_delta

@pytest.fixture(autouse=True)
def setup_db(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_delta.db")
    monkeypatch.setenv("CACHE_DB_PATH", test_db)
    init_db()

def test_compute_git_repo_delta(tmp_path):
    repo_dir = tmp_path / "cloned_repo"
    repo_dir.mkdir()
    (repo_dir / "file1.py").write_text("print('v1')")
    (repo_dir / "file2.py").write_text("print('v2')")

    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO indexed_files (filepath, repo, doc_type, hash) VALUES (?, ?, ?, ?)",
            ("test_repo://file1.py", "test_repo", "code", "old_hash_file1")
        )
        conn.execute(
            "INSERT INTO indexed_files (filepath, repo, doc_type, hash) VALUES (?, ?, ?, ?)",
            ("test_repo://file_deleted.py", "test_repo", "code", "old_hash_deleted")
        )
        conn.commit()

    added, modified, deleted, unchanged = compute_git_repo_delta(str(repo_dir), "test_repo")
    assert "file2.py" in [os.path.relpath(f, str(repo_dir)) for f in added]
    assert "file1.py" in [os.path.relpath(f, str(repo_dir)) for f in modified]
    assert "test_repo://file_deleted.py" in deleted
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_git_incremental.py -v`
Expected: FAIL with `ImportError: cannot import name 'compute_git_repo_delta'`

- [ ] **Step 3: Implement delta computation and incremental sync logic**

In `app/services/indexing/git_syncer.py`:
- Implement `compute_git_repo_delta(temp_dir: str, repo_name: str) -> Tuple[List[str], List[str], List[str], List[str]]`.
- Update `sync_single_git_repo`:
  - Calculate delta ($A, M, D, U$).
  - If $A=0, M=0, D=0$, update `commit_sha` and skip re-indexing.
  - Delete vectors and SQLite rows only for $M$ and $D$.
  - Parse and index only $A$ and $M$ in batches of 25 files.
  - Record SHA256 content hashes in `indexed_files.hash`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_git_incremental.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/indexing/git_syncer.py tests/test_git_incremental.py
git commit -m "feat(indexing): implement file-level SHA256 git delta computation and incremental sync"
```

---

### Task 5: End-to-End Integration Verification & Test Suite

**Files:**
- Test: `tests/test_incremental_pipeline.py`
- Modify: (Any bug fixes discovered during e2e testing)

- [ ] **Step 1: Write end-to-end integration test**

```python
# tests/test_incremental_pipeline.py
import os
import pytest
from app.services.database.connection import init_db, get_db_connection
from app.services.indexing.git_syncer import sync_single_git_repo
from app.services.vector_store import get_vector_store

def test_full_incremental_sync_pipeline(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_pipeline.db")
    monkeypatch.setenv("CACHE_DB_PATH", test_db)
    init_db()

    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO git_repositories (id, name, url, branch, commit_sha, status) VALUES (1, 'mock-repo', 'https://github.com/mock/repo.git', 'main', NULL, 'pending')"
        )
        conn.commit()

    # Verify initial and subsequent sync behavior
```

- [ ] **Step 2: Run full test suite**

Run: `pytest`
Expected: ALL tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_incremental_pipeline.py
git commit -m "test(pipeline): add end-to-end incremental ingestion and caching verification"
```
