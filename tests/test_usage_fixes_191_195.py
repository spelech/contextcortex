"""Regression tests for Issues #191, #192, #193, #194, and #195."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import app.services.database as db_service
import app.services.indexing.git_syncer as git_syncer
import app.services.indexing.index_format as index_format
from app.api.routers.repositories import api_delete_repo
from app.mcp.handlers.diagnostic_handlers import handle_diagnose_issue
from app.mcp.handlers.file_handlers import handle_read_file
from app.mcp.handlers.grep_handlers import handle_grep_code
from app.mcp.handlers.script_handlers import code_mode_limits, handle_execute_script
from app.mcp.handlers.search_handlers import handle_search
from app.mcp.handlers.symbol_handlers import handle_find_symbol, handle_trace_path
from app.services.database.engine import get_db_engine, init_db
from app.services.diagnostic_error_terms import extract_error_terms, is_data_value_token
from app.services.diagnostics import diagnose_issue
from app.services.file_reader import FileReaderService
from app.services.indexing.git_progress import progress_tracker
from app.services.script_sandbox import ScriptLimits, code_mode_available, run_script
from app.services.search import execute_hybrid_search
from app.services.vector_store.base import VectorSearchResult

needs_v8 = pytest.mark.skipif(not code_mode_available(), reason="needs the mini-racer package")


class _InMemoryStore:
    def __init__(self):
        self.docs = {}
        self.deleted_paths = []
        self.upsert_events = []

    def ensure_collection(self):
        return True

    def delete_by_path(self, filepath):
        self.deleted_paths.append(filepath)
        self.docs = {k: d for k, d in self.docs.items() if d.path != filepath}
        return True

    def delete_by_repo(self, repo):
        self.docs = {k: d for k, d in self.docs.items() if getattr(d, "repo", None) != repo}
        return True

    def upsert_documents(self, docs):
        for d in docs:
            self.docs[d.id] = d
            self.upsert_events.append(d.path)
        return True

    def get_file_chunks(self, path, repo=None):
        return []


def _fake_embeddings(texts, *args, **kwargs):
    return [{"dense": [0.1] * 8, "sparse": None} for _ in texts]


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    db_file = tmp_path / "usage_fixes.db"
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("CACHE_DB_PATH", str(db_file))
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", str(db_file))
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", str(db_file), raising=False)
    init_db(engine=get_db_engine(db_url, reset=True))
    progress_tracker.jobs.clear()
    yield tmp_path
    progress_tracker.jobs.clear()


# --- Issue #191: index-format fingerprint on API-added repos and cleanup on delete ---


def test_191_single_repo_sync_marks_fingerprint_so_startup_does_not_force_reindex(isolated_db):
    repo_dir = isolated_db / "clone_191"
    repo_dir.mkdir()
    (repo_dir / "service.py").write_text("def calculate_total(x):\n    return x + 1\n", encoding="utf-8")

    with db_service.get_db_connection() as conn:
        cur = conn.execute(
            "INSERT INTO git_repositories (name, url, branch, status, enabled) VALUES ('api-repo', 'https://example.com/a.git', 'main', 'pending', 1)"
        )
        conn.commit()
        repo_id = cur.lastrowid

    store = _InMemoryStore()
    clone_result = SimpleNamespace(temp_dir=str(repo_dir), commit_sha="aaa11111", error=None)

    with patch("app.services.vector_store.get_vector_store", return_value=store), \
         patch("app.services.indexing.processor.get_hybrid_embeddings_batch", side_effect=_fake_embeddings), \
         patch("app.services.git_manager.get_remote_head_sha", return_value="aaa11111"), \
         patch("app.services.git_manager.shallow_clone_repo", return_value=clone_result), \
         patch("app.services.git_manager.extract_recent_commits", return_value=[]), \
         patch("app.services.git_manager.cleanup_repo_dir"):
        assert git_syncer.sync_single_git_repo(repo_id) is True

    fp = index_format.current_fingerprint()
    assert not index_format.is_stale(f"git:{repo_id}", fp)

    sync_calls = []

    def _record_sync(rid, force=False):
        sync_calls.append((rid, force))
        return True

    with patch("app.services.indexing.local_syncer.sync_local_paths", return_value=True), \
         patch("app.services.indexing.git_syncer.sync_single_git_repo", side_effect=_record_sync):
        git_syncer._sync_all_sources()

    assert sync_calls == [(repo_id, False)]


def test_191_deleting_repo_clears_index_format_fingerprint(isolated_db):
    with db_service.get_db_connection() as conn:
        cur = conn.execute(
            "INSERT INTO git_repositories (name, url, branch, status, enabled) VALUES ('del-repo', 'https://example.com/d.git', 'main', 'synced', 1)"
        )
        conn.commit()
        repo_id = cur.lastrowid

    index_format.mark_current(f"git:{repo_id}", index_format.current_fingerprint())
    assert db_service.get_metadata(f"index_format:git:{repo_id}") is not None

    with patch("app.services.vector_store.get_vector_store", return_value=_InMemoryStore()), \
         patch("app.services.git_manager.cleanup_persistent_repo"):
        res = asyncio.run(api_delete_repo(repo_id))

    assert res["status"] == "success"
    assert db_service.get_metadata(f"index_format:git:{repo_id}") is None


# --- Issue #192: old chunks stay searchable during re-index + sync status in tool responses ---


def test_192_modified_file_keeps_old_chunks_and_symbols_until_batch_persists(isolated_db):
    repo_dir = isolated_db / "clone_192"
    repo_dir.mkdir()
    src = repo_dir / "billing.py"
    src.write_text("def old_price():\n    return 10\n", encoding="utf-8")

    with db_service.get_db_connection() as conn:
        cur = conn.execute(
            "INSERT INTO git_repositories (name, url, branch, status, enabled) VALUES ('shop-repo', 'https://example.com/s.git', 'main', 'pending', 1)"
        )
        conn.commit()
        repo_id = cur.lastrowid

    store = _InMemoryStore()
    clone_v1 = SimpleNamespace(temp_dir=str(repo_dir), commit_sha="11111111", error=None)
    with patch("app.services.vector_store.get_vector_store", return_value=store), \
         patch("app.services.indexing.processor.get_hybrid_embeddings_batch", side_effect=_fake_embeddings), \
         patch("app.services.git_manager.get_remote_head_sha", return_value="11111111"), \
         patch("app.services.git_manager.shallow_clone_repo", return_value=clone_v1), \
         patch("app.services.git_manager.extract_recent_commits", return_value=[]), \
         patch("app.services.git_manager.cleanup_repo_dir"):
        assert git_syncer.sync_single_git_repo(repo_id) is True

    assert len(store.docs) >= 1
    src.write_text("def new_price():\n    return 20\n", encoding="utf-8")

    observed_during_embed = {}

    def _inspect_during_embed(texts, *args, **kwargs):
        # At embedding time (before persist), old vectors & symbols must still be present.
        observed_during_embed["vector_count"] = len(store.docs)
        with db_service.get_db_connection() as conn:
            observed_during_embed["symbols"] = [
                r["name"] for r in conn.execute("SELECT name FROM ast_symbols WHERE repo = 'shop-repo'").fetchall()
            ]
        return _fake_embeddings(texts)

    clone_v2 = SimpleNamespace(temp_dir=str(repo_dir), commit_sha="22222222", error=None)
    with patch("app.services.vector_store.get_vector_store", return_value=store), \
         patch("app.services.indexing.processor.get_hybrid_embeddings_batch", side_effect=_inspect_during_embed), \
         patch("app.services.git_manager.get_remote_head_sha", return_value="22222222"), \
         patch("app.services.git_manager.shallow_clone_repo", return_value=clone_v2), \
         patch("app.services.git_manager.extract_recent_commits", return_value=[]), \
         patch("app.services.git_manager.cleanup_repo_dir"):
        assert git_syncer.sync_single_git_repo(repo_id) is True

    assert observed_during_embed["vector_count"] >= 1
    assert "old_price" in observed_during_embed["symbols"]

    # After persist, old symbol is replaced atomically with the new symbol (no duplicates).
    with db_service.get_db_connection() as conn:
        final_syms = [r["name"] for r in conn.execute("SELECT name FROM ast_symbols WHERE repo = 'shop-repo'").fetchall()]
    assert "new_price" in final_syms
    assert "old_price" not in final_syms


def test_192_search_tools_include_index_status_while_repo_is_syncing(isolated_db):
    progress_tracker.get_or_create_job(42, "shop-repo")
    progress_tracker.update_step(42, 4, "Ingested 120/500", processed=120, total=500)

    fake_reader = MagicMock()
    fake_reader.grep_code.return_value = {"matches": []}

    with patch("app.mcp.handlers.search_handlers.execute_hybrid_search", return_value=[]), \
         patch("app.mcp.handlers.grep_handlers.get_file_reader_service", return_value=fake_reader), \
         patch("app.mcp.handlers.symbol_handlers.trace_symbol_path", return_value=json.dumps({"found": False, "symbol": "Foo"})), \
         patch("app.mcp.handlers.diagnostic_handlers.diagnose_issue", return_value={"call_chain": {"steps": []}, "semantic_candidates": []}):
        s_res = json.loads(asyncio.run(handle_search(query="billing", repo="shop-repo")))
        g_res = json.loads(asyncio.run(handle_grep_code(pattern="billing", repo="shop-repo")))
        f_res = json.loads(asyncio.run(handle_find_symbol(symbol="Foo", repo="shop-repo")))
        t_res = json.loads(asyncio.run(handle_trace_path(symbol="Foo", repo="shop-repo")))
        d_res = json.loads(asyncio.run(handle_diagnose_issue(issue_text="billing fails", repo="shop-repo")))

    for payload in (s_res, g_res, f_res, t_res, d_res):
        assert payload["index_status"] == "syncing"
        assert payload["sync_progress"]["processed"] == 120
        assert payload["sync_progress"]["total"] == 500
    assert s_res["total"] == 0
    assert f_res["total"] == 0

    # Once finished, index_status is omitted.
    progress_tracker.finish_job(42, "synced")
    with patch("app.mcp.handlers.search_handlers.execute_hybrid_search", return_value=[]):
        idle_res = json.loads(asyncio.run(handle_search(query="billing", repo="shop-repo")))
    assert "index_status" not in idle_res
    assert "sync_progress" not in idle_res


# --- Issue #193: diagnose_issue plain-language semantic_candidates + data-value filtering ---


def test_193_plain_language_diagnose_matches_semantic_search_results(isolated_db):
    report = (
        "Customer reports that product 1234-ABCD (SKU-98765) still appears on the catalog page "
        "even when the 'In Stock Only' filter toggle is enabled."
    )
    top_semantic_hits = [
        VectorSearchResult(
            id="hit-1",
            score=0.47,
            dense_score=0.47,
            payload={
                "repo": "shop",
                "doc_type": "code",
                "rel_path": "Services/CatalogAvailabilityFilter.cs",
                "symbol": "CatalogAvailabilityFilter.ApplyInStockFilter",
                "language": "c_sharp",
                "start_line": 15,
                "end_line": 42,
                "content": "public IQueryable<Product> ApplyInStockFilter(IQueryable<Product> q) => q;",
            },
        ),
        VectorSearchResult(
            id="hit-2",
            score=0.44,
            dense_score=0.44,
            payload={
                "repo": "shop",
                "doc_type": "code",
                "rel_path": "Services/InventoryQueryService.cs",
                "symbol": "InventoryQueryService.FilterAvailable",
                "language": "c_sharp",
                "start_line": 10,
                "end_line": 30,
                "content": "public List<Product> FilterAvailable() => new();",
            },
        ),
    ]

    captured = []

    class _SemanticStore:
        mode = "remote"

        def get_capabilities(self):
            return {"search_modes": ["hybrid", "semantic", "lexical"]}

        def search(self, **kwargs):
            captured.append(kwargs)
            assert kwargs["search_mode"] in ("semantic", "hybrid")
            return list(top_semantic_hits)

    with patch("app.services.search.get_vector_store", return_value=_SemanticStore()), \
         patch("app.services.search._enrich_code_ast_metadata"), \
         patch("app.services.search.run_fast_lexical_track", return_value=[]):
        search_hits = execute_hybrid_search(report, doc_type="code", repo="shop", limit=5, search_mode="semantic")
        diag = diagnose_issue(report, repo="shop", limit=5)

    assert len(captured) >= 2
    # Plain-language diagnose queries must NOT include raw product codes or SKU data values.
    for call_kw in captured[1:]:
        assert "1234-ABCD" not in call_kw["query_text"]
        assert "SKU-98765" not in call_kw["query_text"]
    search_files = [h.payload["rel_path"] for h in search_hits]
    diag_files = [c["file"] for c in diag["semantic_candidates"]]
    assert diag_files[:2] == search_files[:2]
    assert diag["queries"] and diag["areas"]


def test_193_error_terms_exclude_alphanumeric_data_values_but_keep_cobol_and_code():
    assert is_data_value_token("1234-ABCD") is True
    assert is_data_value_token("SKU-98765") is True
    assert is_data_value_token("a1b2c3d4") is True
    assert is_data_value_token("1000-CALC-TAX") is False
    assert is_data_value_token("OrderService") is False

    terms = extract_error_terms(
        "Product 1234-ABCD and SKU-98765 failed in OrderService with correlation id a1b2c3d4e5"
    )
    assert "1234-abcd" not in terms
    assert "sku-98765" not in terms
    assert "a1b2c3d4e5" not in terms
    assert "orderservice" in terms


# --- Issue #194: read_file distinguishes missing path from ephemeral clone reconstruction failure ---


def test_194_read_file_nonexistent_path_in_ephemeral_repo_says_not_in_repo_with_suggestions(isolated_db, monkeypatch):
    empty_clones = isolated_db / "empty_persistent"
    empty_clones.mkdir()
    monkeypatch.setattr("app.services.git_manager.PERSISTENT_REPOS_DIR", str(empty_clones))

    with db_service.get_db_connection() as conn:
        conn.execute(
            "INSERT INTO git_repositories (name, url, branch, status, enabled, keep_shallow) "
            "VALUES ('ephem-repo', 'https://example.com/e.git', 'main', 'synced', 1, 0)"
        )
        conn.execute(
            "INSERT INTO indexed_files (filepath, repo, doc_type, language) VALUES "
            "('ephem-repo://Tests/OrderServiceTests.cs', 'ephem-repo', 'code', 'c_sharp'), "
            "('ephem-repo://Src/ExistingFile.cs', 'ephem-repo', 'code', 'c_sharp')"
        )
        conn.commit()

    reader = FileReaderService(storage_root=str(isolated_db / "storage"))

    with patch("app.services.vector_store.get_vector_store", return_value=_InMemoryStore()):
        # Case 1: path is NOT in indexed_files -> clear "not found in repository" error + suggestion, NO keep_shallow/(not indexed)
        with pytest.raises(FileNotFoundError) as exc_missing:
            reader.read_file("Src/OrderService.cs", repo="ephem-repo")
        msg_missing = str(exc_missing.value)
        assert "not found in repository 'ephem-repo'" in msg_missing
        assert "(not indexed)" not in msg_missing
        assert "keep_shallow" not in msg_missing
        assert "Tests/OrderServiceTests.cs" in msg_missing

        # Case 2: path IS in indexed_files but chunks cannot reconstruct it -> keep_shallow message preserved
        with pytest.raises(FileNotFoundError) as exc_indexed:
            reader.read_file("Src/ExistingFile.cs", repo="ephem-repo")
        msg_indexed = str(exc_indexed.value)
        assert "keep_shallow" in msg_indexed
        assert "ephemeral Git clone" in msg_indexed


def test_194_mcp_handle_read_file_surfaces_not_in_repo_message(isolated_db, monkeypatch):
    empty_clones = isolated_db / "empty_persistent_mcp"
    empty_clones.mkdir()
    monkeypatch.setattr("app.services.git_manager.PERSISTENT_REPOS_DIR", str(empty_clones))

    with db_service.get_db_connection() as conn:
        conn.execute(
            "INSERT INTO git_repositories (name, url, branch, status, enabled, keep_shallow) "
            "VALUES ('ephem-repo', 'https://example.com/e.git', 'main', 'synced', 1, 0)"
        )
        conn.commit()

    reader = FileReaderService(storage_root=str(isolated_db / "storage_mcp"))
    with patch("app.mcp.handlers.file_handlers.get_file_reader_service", return_value=reader), \
         patch("app.services.vector_store.get_vector_store", return_value=_InMemoryStore()):
        payload = json.loads(asyncio.run(handle_read_file(path="Src/DoesNotExist.cs", repo="ephem-repo")))
    assert "not found in repository 'ephem-repo'" in payload["error"]
    assert "(not indexed)" not in payload["error"]
    assert "keep_shallow" not in payload["error"]


# --- Issue #195: execute_script timeout returns partial_results + guidance + 60s default ---


def test_195_default_timeout_is_60s_and_description_documents_budget(monkeypatch):
    monkeypatch.delenv("CODE_MODE_TIMEOUT_SECONDS", raising=False)
    assert code_mode_limits().timeout_seconds == 60.0

    from mcp.server.fastmcp import FastMCP
    from app.mcp.tools import register_mcp_tools_and_resources

    server = register_mcp_tools_and_resources(FastMCP("BudgetDoc"))
    tools = {t.name: t for t in server._tool_manager.list_tools()}
    desc = tools["execute_script"].description
    assert "60 s" in desc
    assert "partial_results" in desc


@needs_v8
def test_195_timeout_returns_completed_partial_results_and_guidance():
    async def _slow_third_tool(name, tool_args):
        if tool_args.get("slow"):
            await asyncio.sleep(5)
        return {"hit": tool_args.get("q")}

    script = """
console.log('step 1');
const a = await tools.search({q: 'first'});
console.log('step 2');
const b = await tools.search({q: 'second'});
const c = await tools.search({q: 'third', slow: true});
return [a, b, c];
"""
    outcome = asyncio.run(run_script(script, {}, _slow_third_tool, ScriptLimits(timeout_seconds=0.8)))
    assert not outcome.ok
    assert "2 of 3 nested tool calls completed" in outcome.error
    assert "Split the script" in outcome.error
    assert outcome.tool_calls_count == 3
    assert outcome.logs == ["step 1", "step 2"]
    assert len(outcome.partial_results) == 3
    assert outcome.partial_results[0]["status"] == "ok"
    assert outcome.partial_results[0]["result"] == {"hit": "first"}
    assert outcome.partial_results[1]["status"] == "ok"
    assert outcome.partial_results[1]["result"] == {"hit": "second"}
    assert outcome.partial_results[2]["status"] == "timed_out"


@needs_v8
def test_195_handle_execute_script_includes_partial_results_on_timeout(monkeypatch):
    monkeypatch.setenv("CODE_MODE_TIMEOUT_SECONDS", "1")

    async def _fake_call(name, tool_args):
        if tool_args.get("slow"):
            await asyncio.sleep(5)
        return {"found": tool_args.get("q")}

    script = """
const a = await tools.search({q: 'alpha'});
const b = await tools.search({q: 'beta', slow: true});
return [a, b];
"""
    with patch("app.mcp.handlers.script_handlers.call_tool_from_script", side_effect=_fake_call):
        payload = json.loads(asyncio.run(handle_execute_script(script=script)))

    assert payload["error"] == "script_failed"
    assert "1 of 2 nested tool calls completed" in payload["message"]
    assert payload["partial_results"][0]["result"] == {"found": "alpha"}
    assert payload["partial_results"][1]["status"] == "timed_out"
