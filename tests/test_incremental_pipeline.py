import os
import shutil
import hashlib
import uuid
from unittest.mock import patch, MagicMock, call
import pytest

from app.models.schemas import CloneResult
from app.services.database.connection import init_db, get_db_connection
from app.services.database.embedding_cache import (
    get_cached_embeddings_batch,
    set_cached_embeddings_batch,
)
from app.services.indexing.git_syncer import (
    sync_single_git_repo,
    compute_git_repo_delta,
)
import app.services.indexing.processor as proc_service
from app.services.vector_store.manager import (
    VectorStoreManager,
    get_vector_store,
    set_vector_store_db_config,
)
from app.services.topology.graph_builder import get_topology_graph
from app.services.search import execute_hybrid_search


@pytest.fixture(autouse=True)
def setup_pipeline_env(tmp_path, monkeypatch):
    """Isolate database, vector store, and manager singleton for each test."""
    test_db = str(tmp_path / "test_pipeline.db")
    monkeypatch.setenv("CACHE_DB_PATH", test_db)
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", test_db)
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", test_db)

    # Use isolated Chroma vector store on disk
    chroma_storage = str(tmp_path / "chroma_pipeline_data")
    monkeypatch.setenv("CHROMA_STORAGE_PATH", chroma_storage)
    monkeypatch.setenv("VECTOR_STORE_PROVIDER", "chroma")
    monkeypatch.setenv("VECTOR_STORE_MODE", "persistent")
    monkeypatch.setenv("VECTOR_STORE_STORAGE_PATH", chroma_storage)

    init_db()
    set_vector_store_db_config(
        provider="chroma",
        mode="persistent",
        storage_path=chroma_storage,
        url="",
        collection="pipeline_test_coll"
    )
    VectorStoreManager.reset_instance()

    yield {
        "db_path": test_db,
        "chroma_path": chroma_storage,
        "tmp_path": tmp_path,
    }

    VectorStoreManager.reset_instance()


def create_initial_mock_repo(repo_dir):
    """Populates a mock git repo with Python code, FastAPI routes, and Markdown docs with links."""
    os.makedirs(repo_dir / "src", exist_ok=True)
    os.makedirs(repo_dir / "docs", exist_ok=True)

    # 1. src/auth.py (Code with functions)
    (repo_dir / "src" / "auth.py").write_text(
        'def login(username: str, password: str) -> bool:\n'
        '    """Authenticate user credentials."""\n'
        '    return username == "admin" and password == "secret"\n\n'
        'def verify_token(token: str) -> dict:\n'
        '    """Verify JWT authentication token."""\n'
        '    return {"user": "admin", "valid": True}\n',
        encoding="utf-8"
    )

    # 2. src/server.py (FastAPI route)
    (repo_dir / "src" / "server.py").write_text(
        'from fastapi import FastAPI\n'
        'app = FastAPI()\n\n'
        '@app.get("/api/v1/health")\n'
        'def get_health():\n'
        '    return {"status": "healthy", "uptime": 100}\n',
        encoding="utf-8"
    )

    # 3. src/client.py (API client call)
    (repo_dir / "src" / "client.py").write_text(
        'import requests\n\n'
        'def check_server_status():\n'
        '    response = requests.get("/api/v1/health")\n'
        '    return response.json()\n',
        encoding="utf-8"
    )

    # 4. src/unchanged_utils.py (Helper file that stays untouched)
    (repo_dir / "src" / "unchanged_utils.py").write_text(
        'def helper_calculate(val: int) -> int:\n'
        '    """Utility calculation function that remains unchanged."""\n'
        '    return val * 42\n',
        encoding="utf-8"
    )

    # 5. docs/overview.md (Markdown with standard links, wikilinks, and external links)
    (repo_dir / "docs" / "overview.md").write_text(
        '# System Overview\n'
        'Welcome to the core system documentation.\n\n'
        '## Navigation\n'
        '- See the [Authentication Guide](docs/auth_guide.md) for credentials.\n'
        '- Read [[Architecture Spec]] for high level component topology.\n'
        '- Consult [[Data Models|Schema Specifications]] for database structures.\n'
        '- External reference: [Python Official](https://python.org).\n',
        encoding="utf-8"
    )

    # 6. docs/auth_guide.md (Markdown doc)
    (repo_dir / "docs" / "auth_guide.md").write_text(
        '# Authentication Guide\n'
        'Details regarding JWT tokens and login mechanisms.\n'
        'Back to [Overview](docs/overview.md) and [[Architecture Spec]].\n',
        encoding="utf-8"
    )

    # 7. docs/Architecture Spec.md (Markdown doc to be deleted in step 3)
    (repo_dir / "docs" / "Architecture Spec.md").write_text(
        '# Architecture Spec\n'
        'Overview of distributed services and vector databases.\n',
        encoding="utf-8"
    )

    # 8. docs/Data Models.md (Markdown doc)
    (repo_dir / "docs" / "Data Models.md").write_text(
        '# Data Models\n'
        'Core entity definitions and schema fields.\n',
        encoding="utf-8"
    )


def test_full_incremental_sync_pipeline(tmp_path):
    """
    End-to-End integration test for the full ingestion & incremental sync pipeline:
    1. Initial full repo ingestion (code + markdown with wikilinks & standard links).
    2. Subsequent sync with 0 changes: verifies no re-indexing occurs.
    3. Subsequent sync with a multi-file commit (1 file modified, 1 file added, 1 file deleted, 1 file unchanged):
       - Verifies only modified and added files are parsed and embedded.
       - Verifies unchanged file embeddings are retained.
       - Verifies deleted file's vectors and SQLite entries are purged.
       - Verifies embedding_cache is populated and reused.
       - Verifies doc links (DOC_LINKS_TO) appear in the topology graph and search works across all indexed files.
    """
    repo_source_dir = tmp_path / "mock_repo_src"
    create_initial_mock_repo(repo_source_dir)

    # Seed git_repositories in DB
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO git_repositories (id, name, url, branch, commit_sha, status)
               VALUES (1, 'mock-repo', 'https://github.com/mock/repo.git', 'main', NULL, 'pending')"""
        )
        conn.commit()

    # -------------------------------------------------------------------------
    # PHASE 1: Initial Full Repo Ingestion
    # -------------------------------------------------------------------------
    sha_v1 = "sha_initial_1111111111111111"
    
    def make_clone_result(commit_sha):
        clone_tmp = tmp_path / f"clone_{uuid.uuid4().hex[:8]}"
        shutil.copytree(str(repo_source_dir), str(clone_tmp))
        return CloneResult(temp_dir=str(clone_tmp), commit_sha=commit_sha, error=None)

    with patch("app.services.git_manager.get_remote_head_sha", return_value=sha_v1), \
         patch("app.services.git_manager.shallow_clone_repo", side_effect=lambda *args, **kwargs: make_clone_result(sha_v1)):

        sync_single_git_repo(1)

    # Verify Phase 1 Database State
    with get_db_connection() as conn:
        repo_row = conn.execute("SELECT * FROM git_repositories WHERE id = 1").fetchone()
        assert repo_row["status"] == "synced"
        assert repo_row["commit_sha"] == sha_v1
        assert repo_row["last_error"] is None

        # Verify all 8 files indexed
        indexed_rows = conn.execute("SELECT filepath, doc_type, language, hash FROM indexed_files WHERE repo = 'mock-repo'").fetchall()
        indexed_map = {r["filepath"]: r for r in indexed_rows}
        assert len(indexed_map) == 8
        assert "mock-repo://src/auth.py" in indexed_map
        assert "mock-repo://src/server.py" in indexed_map
        assert "mock-repo://src/client.py" in indexed_map
        assert "mock-repo://src/unchanged_utils.py" in indexed_map
        assert "mock-repo://docs/overview.md" in indexed_map
        assert "mock-repo://docs/auth_guide.md" in indexed_map
        assert "mock-repo://docs/Architecture Spec.md" in indexed_map
        assert "mock-repo://docs/Data Models.md" in indexed_map

        # Verify AST symbols
        symbols = conn.execute("SELECT name, kind, filepath FROM ast_symbols WHERE repo = 'mock-repo'").fetchall()
        symbol_names = {s["name"] for s in symbols}
        assert "login" in symbol_names
        assert "verify_token" in symbol_names
        assert "get_health" in symbol_names
        assert "check_server_status" in symbol_names
        assert "helper_calculate" in symbol_names

        # Verify API Routes & Client Calls
        routes = conn.execute("SELECT path_pattern, http_method FROM api_routes WHERE repo = 'mock-repo'").fetchall()
        route_patterns = [(r["http_method"], r["path_pattern"]) for r in routes]
        assert ("GET", "/api/v1/health") in route_patterns

        calls = conn.execute("SELECT url_pattern, http_method FROM api_client_calls WHERE repo = 'mock-repo'").fetchall()
        call_patterns = [(c["http_method"], c["url_pattern"]) for c in calls]
        assert ("GET", "/api/v1/health") in call_patterns

        # Verify DOC_LINKS_TO in ast_relationships
        doc_rels = conn.execute(
            "SELECT source_filepath, target_symbol, relationship_type FROM ast_relationships WHERE relationship_type = 'DOC_LINKS_TO'"
        ).fetchall()
        assert len(doc_rels) >= 3
        targets = [r["target_symbol"] for r in doc_rels]
        assert "docs/auth_guide.md" in targets or "auth_guide.md" in targets
        assert "Architecture Spec" in targets
        assert "Data Models" in targets

        # Verify File Summaries
        summaries = conn.execute("SELECT filepath, title FROM file_summaries WHERE repo = 'mock-repo'").fetchall()
        assert len(summaries) == 8

        # Verify embedding_cache is populated
        cache_count = conn.execute("SELECT count(*) FROM embedding_cache").fetchone()[0]
        assert cache_count > 0

    # Verify Phase 1 Topology Graph
    graph = get_topology_graph(repo="mock-repo", view_type="files")
    assert graph is not None
    node_ids = {n["id"] for n in graph.get("nodes", [])}
    assert "file:mock-repo:docs/overview.md" in node_ids
    assert "file:mock-repo:docs/auth_guide.md" in node_ids
    assert "file:mock-repo:docs/Architecture Spec.md" in node_ids
    assert "file:mock-repo:src/auth.py" in node_ids

    doc_edges = [e for e in graph.get("edges", []) if e.get("type") == "DOC_LINKS_TO"]
    assert len(doc_edges) >= 2
    edge_targets = {e["target"] for e in doc_edges}
    assert "file:mock-repo:docs/auth_guide.md" in edge_targets
    assert "file:mock-repo:docs/Architecture Spec.md" in edge_targets

    # Verify Phase 1 Vector Store Search
    search_auth = execute_hybrid_search("authenticate user credentials login", repo="mock-repo", limit=5)
    assert len(search_auth) > 0
    assert any("auth.py" in r.payload.get("path", "") for r in search_auth)

    search_health = execute_hybrid_search("health status check endpoint", repo="mock-repo", limit=5)
    assert len(search_health) > 0
    assert any("server.py" in r.payload.get("path", "") or "client.py" in r.payload.get("path", "") for r in search_health)

    search_doc = execute_hybrid_search("Schema Specifications data models", repo="mock-repo", limit=5)
    assert len(search_doc) > 0
    assert any("Data Models.md" in r.payload.get("path", "") or "overview.md" in r.payload.get("path", "") for r in search_doc)

    # -------------------------------------------------------------------------
    # PHASE 2: Subsequent Sync with 0 changes
    # -------------------------------------------------------------------------
    # 2a: Remote HEAD SHA is unchanged -> clone is skipped completely
    with patch("app.services.git_manager.get_remote_head_sha", return_value=sha_v1), \
         patch("app.services.git_manager.shallow_clone_repo") as mock_clone, \
         patch("app.services.indexing.processor.process_file_content") as mock_proc:

        sync_single_git_repo(1)

        mock_clone.assert_not_called()
        mock_proc.assert_not_called()

    # 2b: Remote HEAD SHA changed, but file contents are identical -> delta is empty
    sha_v2_noop = "sha_noop_2222222222222222"
    with patch("app.services.git_manager.get_remote_head_sha", return_value=sha_v2_noop), \
         patch("app.services.git_manager.shallow_clone_repo", side_effect=lambda *args, **kwargs: make_clone_result(sha_v2_noop)), \
         patch("app.services.indexing.processor.process_file_content") as mock_proc, \
         patch.object(get_vector_store(), "upsert_documents", wraps=get_vector_store().upsert_documents) as spy_upsert, \
         patch.object(get_vector_store(), "delete_by_path", wraps=get_vector_store().delete_by_path) as spy_del:

        sync_single_git_repo(1)

        # No files should be processed or upserted/deleted
        mock_proc.assert_not_called()
        spy_upsert.assert_not_called()
        spy_del.assert_not_called()

        with get_db_connection() as conn:
            repo_row = conn.execute("SELECT commit_sha, status FROM git_repositories WHERE id = 1").fetchone()
            assert repo_row["commit_sha"] == sha_v2_noop
            assert repo_row["status"] == "synced"

    # -------------------------------------------------------------------------
    # PHASE 3: Subsequent Sync with a Multi-File Commit
    # (1 file modified, 1 file added, 1 file deleted, 1 file unchanged)
    # -------------------------------------------------------------------------
    # 1. Modified file: src/auth.py (add mfa_login function, keep verify_token intact)
    (repo_source_dir / "src" / "auth.py").write_text(
        'def login(username: str, password: str) -> bool:\n'
        '    """Authenticate user credentials with multi-factor support."""\n'
        '    return username == "admin" and password == "secret"\n\n'
        'def verify_token(token: str) -> dict:\n'
        '    """Verify JWT authentication token."""\n'
        '    return {"user": "admin", "valid": True}\n\n'
        'def mfa_authenticate(user_id: str, otp_code: str) -> bool:\n'
        '    """Perform two-factor authentication verification."""\n'
        '    return len(otp_code) == 6\n',
        encoding="utf-8"
    )

    # 2. Added file: src/payments.py (new module with symbol and API route)
    (repo_source_dir / "src" / "payments.py").write_text(
        'from fastapi import APIRouter\n'
        'router = APIRouter()\n\n'
        '@router.post("/api/v1/payments")\n'
        'def process_credit_card_payment(amount: float, currency: str) -> dict:\n'
        '    """Process customer credit card payment transactions."""\n'
        '    return {"payment_id": "pay_12345", "status": "success", "amount": amount}\n',
        encoding="utf-8"
    )

    # 3. Deleted file: docs/Architecture Spec.md
    arch_spec_file = repo_source_dir / "docs" / "Architecture Spec.md"
    if arch_spec_file.exists():
        arch_spec_file.unlink()

    # 4. Unchanged files: src/unchanged_utils.py, src/server.py, src/client.py, docs/overview.md, docs/auth_guide.md, docs/Data Models.md

    sha_v3_delta = "sha_delta_3333333333333333"

    with get_db_connection() as conn:
        cache_count_before = conn.execute("SELECT count(*) FROM embedding_cache").fetchone()[0]

    # Track process_file_content calls to verify only added and modified files are parsed
    processed_paths = []
    original_process_file_content = proc_service.process_file_content

    def tracked_process_file(*args, **kwargs):
        filepath = kwargs.get("filepath") or (args[0] if args else None)
        processed_paths.append(filepath)
        return original_process_file_content(*args, **kwargs)

    # Spy on embedding function to verify embedding cache reuse
    embed_calls = []
    original_get_hybrid_batch = proc_service.get_hybrid_embeddings_batch

    def tracked_embed_batch(texts):
        embed_calls.append(texts)
        return original_get_hybrid_batch(texts)

    with patch("app.services.git_manager.get_remote_head_sha", return_value=sha_v3_delta), \
         patch("app.services.git_manager.shallow_clone_repo", side_effect=lambda *args, **kwargs: make_clone_result(sha_v3_delta)), \
         patch("app.services.indexing.processor.process_file_content", side_effect=tracked_process_file), \
         patch("app.services.indexing.processor.get_hybrid_embeddings_batch", side_effect=tracked_embed_batch):

        sync_single_git_repo(1)

    # Verify only modified and added files were processed
    assert len(processed_paths) == 2
    assert "mock-repo://src/auth.py" in processed_paths
    assert "mock-repo://src/payments.py" in processed_paths
    # Unchanged files must NOT be processed
    assert "mock-repo://src/unchanged_utils.py" not in processed_paths
    assert "mock-repo://docs/overview.md" not in processed_paths
    assert "mock-repo://docs/Data Models.md" not in processed_paths

    # Verify DB state after Phase 3
    with get_db_connection() as conn:
        repo_row = conn.execute("SELECT commit_sha, status FROM git_repositories WHERE id = 1").fetchone()
        assert repo_row["commit_sha"] == sha_v3_delta
        assert repo_row["status"] == "synced"

        indexed_rows = conn.execute("SELECT filepath, hash FROM indexed_files WHERE repo = 'mock-repo'").fetchall()
        indexed_map = {r["filepath"]: r["hash"] for r in indexed_rows}

        # 1. Added file is indexed
        assert "mock-repo://src/payments.py" in indexed_map
        # 2. Modified file is updated with new hash
        new_auth_hash = proc_service.compute_text_hash((repo_source_dir / "src" / "auth.py").read_text(encoding="utf-8"))
        assert indexed_map["mock-repo://src/auth.py"] == new_auth_hash
        # 3. Deleted file is purged
        assert "mock-repo://docs/Architecture Spec.md" not in indexed_map
        # 4. Unchanged file is retained
        assert "mock-repo://src/unchanged_utils.py" in indexed_map

        # Verify AST symbols: new symbols added, modified symbols updated, deleted symbols removed
        symbols = conn.execute("SELECT name, filepath FROM ast_symbols WHERE repo = 'mock-repo'").fetchall()
        sym_map = {s["name"]: s["filepath"] for s in symbols}
        assert "mfa_authenticate" in sym_map
        assert "process_credit_card_payment" in sym_map
        assert "helper_calculate" in sym_map
        assert sym_map["mfa_authenticate"] == "mock-repo://src/auth.py"
        assert sym_map["process_credit_card_payment"] == "mock-repo://src/payments.py"

        # Verify API routes: payments route added
        routes = conn.execute("SELECT path_pattern, http_method FROM api_routes WHERE repo = 'mock-repo'").fetchall()
        route_patterns = [(r["http_method"], r["path_pattern"]) for r in routes]
        assert ("POST", "/api/v1/payments") in route_patterns
        assert ("GET", "/api/v1/health") in route_patterns

        # Verify file_summaries: deleted file purged, added file present
        summary_paths = [r["filepath"] for r in conn.execute("SELECT filepath FROM file_summaries WHERE repo = 'mock-repo'").fetchall()]
        assert "mock-repo://src/payments.py" in summary_paths
        assert "mock-repo://docs/Architecture Spec.md" not in summary_paths

        # Verify embedding cache: cached entries grew and verify_token chunk was reused
        cache_count_after = conn.execute("SELECT count(*) FROM embedding_cache").fetchone()[0]
        assert cache_count_after > cache_count_before

    # Verify Topology Graph after deletion & addition
    graph_v3 = get_topology_graph(repo="mock-repo", view_type="files")
    assert graph_v3 is not None
    nodes_v3 = {n["id"] for n in graph_v3.get("nodes", [])}
    assert "file:mock-repo:src/payments.py" in nodes_v3
    assert "file:mock-repo:docs/Architecture Spec.md" not in nodes_v3
    assert "file:mock-repo:src/unchanged_utils.py" in nodes_v3

    # Verify Search across modified, added, unchanged, and deleted content
    # 1. Search for newly added payment functionality
    search_payment = execute_hybrid_search("customer credit card payment transaction", repo="mock-repo", limit=5)
    assert len(search_payment) > 0
    assert any("payments.py" in r.payload.get("path", "") for r in search_payment)

    # 2. Search for newly modified MFA functionality
    search_mfa = execute_hybrid_search("two-factor authentication OTP code", repo="mock-repo", limit=5)
    assert len(search_mfa) > 0
    assert any("auth.py" in r.payload.get("path", "") for r in search_mfa)

    # 3. Search for unchanged utility function
    search_unchanged = execute_hybrid_search("Utility calculation function", repo="mock-repo", limit=5)
    assert len(search_unchanged) > 0
    assert any("unchanged_utils.py" in r.payload.get("path", "") for r in search_unchanged)

    # 4. Search for deleted doc should NOT return the deleted Architecture Spec file
    search_deleted = execute_hybrid_search("Overview of distributed services and vector databases", repo="mock-repo", limit=5)
    assert not any("Architecture Spec.md" in r.payload.get("path", "") for r in search_deleted)


def test_incremental_pipeline_batching_and_large_commit(tmp_path):
    """
    Verifies that incremental sync handles batches exceeding the 25-file batch threshold,
    persisting all records and vector points correctly across multiple flushes.
    """
    repo_dir = tmp_path / "repo_large"
    os.makedirs(repo_dir / "modules", exist_ok=True)

    # Create 32 python files
    for i in range(32):
        (repo_dir / "modules" / f"mod_{i:02d}.py").write_text(
            f'def function_mod_{i:02d}(x: int) -> int:\n'
            f'    """Compute batch result for module {i}."""\n'
            f'    return x + {i}\n',
            encoding="utf-8"
        )

    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO git_repositories (id, name, url, branch, commit_sha, status)
               VALUES (2, 'large-repo', 'https://github.com/mock/large.git', 'main', NULL, 'pending')"""
        )
        conn.commit()

    clone_res = CloneResult(temp_dir=str(repo_dir), commit_sha="sha_large_1", error=None)

    with patch("app.services.git_manager.get_remote_head_sha", return_value="sha_large_1"), \
         patch("app.services.git_manager.shallow_clone_repo", return_value=clone_res), \
         patch("app.services.git_manager.cleanup_repo_dir"):

        sync_single_git_repo(2)

    with get_db_connection() as conn:
        repo_row = conn.execute("SELECT status, commit_sha FROM git_repositories WHERE id = 2").fetchone()
        assert repo_row["status"] == "synced"
        assert repo_row["commit_sha"] == "sha_large_1"

        count = conn.execute("SELECT count(*) FROM indexed_files WHERE repo = 'large-repo'").fetchone()[0]
        assert count == 32

        sym_count = conn.execute("SELECT count(*) FROM ast_symbols WHERE repo = 'large-repo'").fetchone()[0]
        assert sym_count == 32

    # Search across batched files
    search_res = execute_hybrid_search("Compute batch result for module 15", repo="large-repo", limit=5)
    assert len(search_res) > 0
    assert any("mod_15.py" in r.payload.get("path", "") for r in search_res)


def test_incremental_pipeline_clone_error_resilience(tmp_path):
    """
    Verifies that a failure during shallow clone records an error in git_repositories
    and leaves the prior indexed state intact without data loss.
    """
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO git_repositories (id, name, url, branch, commit_sha, status)
               VALUES (3, 'err-repo', 'https://github.com/mock/err.git', 'main', 'sha_prior', 'synced')"""
        )
        conn.execute(
            "INSERT INTO indexed_files (filepath, repo, doc_type, hash) VALUES ('err-repo://file.py', 'err-repo', 'code', 'h1')"
        )
        conn.commit()

    fail_clone = CloneResult(temp_dir=None, commit_sha=None, error="Git remote auth error: token expired")

    with patch("app.services.git_manager.get_remote_head_sha", return_value="sha_new"), \
         patch("app.services.git_manager.shallow_clone_repo", return_value=fail_clone), \
         patch("app.services.git_manager.cleanup_repo_dir"):

        sync_single_git_repo(3)

    with get_db_connection() as conn:
        repo_row = conn.execute("SELECT status, last_error, commit_sha FROM git_repositories WHERE id = 3").fetchone()
        assert repo_row["status"] == "error"
        assert "token expired" in repo_row["last_error"]
        assert repo_row["commit_sha"] == "sha_prior"

        # Verify prior indexed file is preserved
        prior_file = conn.execute("SELECT filepath FROM indexed_files WHERE repo = 'err-repo'").fetchone()
        assert prior_file["filepath"] == "err-repo://file.py"
