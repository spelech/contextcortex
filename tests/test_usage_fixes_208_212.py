"""Regression tests for issues #208, #209, #210, #211, and #212."""

import asyncio
import json
import logging
import socket
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.mcp.handlers.search_handlers import handle_search
from app.mcp.tools import get_tool_definitions
from app.services import listen_sockets
from app.services.database import get_db_connection, get_db_engine, init_db
from app.services.indexing.git_progress import GitProgressTracker
from app.services.indexing.git_syncer import (
    _get_repo_lock, _repo_sync_key, get_active_sync_repos, register_active_sync_repo, unregister_active_sync_repo,
)
from app.services.indexing.state import is_indexing
from app.services.indexing.sync_progress_reporter import (
    BatchProgressMonitor, compute_eta_seconds, format_duration, format_sync_completion_summary,
)
from app.services.lexical_retriever import _query_ast_candidates
from app.services.query_router import classify_query_intent, should_early_return_lexical
from app.services.search import execute_hybrid_search
from app.services.vector_store.base import VectorDocument, VectorSearchResult
from app.services.vector_store.chroma_queries import execute_chroma_grep_chunks
from app.services.vector_store.manager import VectorStoreManager
from app.services.vector_store.pgvector_chunk_scanner import (
    _translate_python_regex_for_postgres, execute_pgvector_dense_query,
    execute_pgvector_file_chunks, execute_pgvector_files_chunks_batch, execute_pgvector_grep_chunks,
)
from app.services.vector_store.pgvector_queries import execute_pgvector_search
from app.services.vector_store.pgvector_schema import ensure_pgvector_collection
from app.services.vector_store.pgvector_store import PgVectorStore
from app.services.vector_store.qdrant_queries import execute_qdrant_grep_chunks


class _Ctx:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def begin(self):
        return self

    def begin_nested(self):
        return self

    def execution_options(self, **_kw):
        return self


# --- Issue #208: non-blocking FTS migration, /ready migrating status, Windows loop ---

def test_208_pgvector_schema_migration_logs_and_builds_new_fts_before_drop(caplog):
    executed_sql, observed_statuses = [], []

    class FakeConn(_Ctx):
        def execute(self, stmt, params=None):
            s = str(stmt).strip()
            executed_sql.append(s)
            if VectorStoreManager.get_migration_status():
                observed_statuses.append(VectorStoreManager.get_migration_status())
            res = MagicMock()
            res.fetchone.return_value = (1536,) if "SELECT atttypmod" in s else None
            res.fetchall.return_value = [("collection_name",), ("id",)] if "i.indisprimary" in s else []
            if "FROM pg_extension" in s or "attname = 'collection_name'" in s:
                res.scalar.return_value = 1
            elif "SELECT EXISTS (SELECT 1 FROM" in s:
                res.scalar.return_value = True
            elif "attname = 'fts'" in s:
                res.scalar.return_value = None
            elif "FROM pg_indexes" in s:
                idx = (params or {}).get("idx", "")
                if idx == "idx_vector_documents_fts":
                    res.scalar.return_value = "CREATE INDEX idx_vector_documents_fts ON vector_documents USING gin (to_tsvector('simple', content))"
                elif idx in ("idx_vector_documents_embedding", "idx_vector_documents_collection", "idx_vector_documents_repo", "idx_vector_documents_type", "idx_vector_documents_path"):
                    res.scalar.return_value = "CREATE INDEX ..."
                else:
                    res.scalar.return_value = None
            return res

    fake_engine = MagicMock()
    fake_engine.dialect.name = "postgresql"
    fake_engine.connect.side_effect = lambda: FakeConn()

    with caplog.at_level(logging.INFO, logger="contextcortex.vector_store.pgvector"):
        assert ensure_pgvector_collection(fake_engine, "vector_documents", 1536) is True

    assert VectorStoreManager.get_migration_status() is None
    assert any("Adding stored FTS column" in s for s in observed_statuses)
    assert "Adding stored FTS column to 'vector_documents'" in caplog.text
    assert "Finished adding stored FTS column" in caplog.text
    create_new = next(i for i, s in enumerate(executed_sql) if "idx_vector_documents_fts_stored" in s and "CREATE INDEX" in s)
    drop_old = next(i for i, s in enumerate(executed_sql) if "DROP INDEX" in s and "idx_vector_documents_fts" in s)
    assert create_new < drop_old
    assert any("idx_vector_documents_coll_repo_rel_path" in s and "(collection_name, repo, rel_path)" in s for s in executed_sql)


def test_208_ready_and_stats_return_migrating_without_blocking():
    import main as main_mod

    VectorStoreManager.set_migration_status("Adding stored FTS column to 'vector_documents'...")
    try:
        client = TestClient(main_mod.app)
        res = client.get("/ready")
        assert res.status_code == 503
        assert res.json()["status"] == "migrating"
        assert "FTS column" in res.json()["migration"]

        with patch("app.services.vector_store.get_vector_store", side_effect=AssertionError("must not block")):
            stats = client.get("/admin/api/stats")
            assert stats.status_code == 200
            assert stats.json()["vector_db_status"] == "Migrating"
            assert stats.json()["vector_store"]["migrating"] is True
    finally:
        VectorStoreManager.set_migration_status(None)


def test_208_windows_uses_selector_event_loop_override(monkeypatch):
    monkeypatch.setattr(listen_sockets.sys, "platform", "win32")
    monkeypatch.delenv("CONTEXTCORTEX_WINDOWS_PROACTOR", raising=False)
    assert listen_sockets._windows_loop_override() == "app.services.listen_sockets:selector_loop_factory"
    loop = listen_sockets.selector_loop_factory()
    try:
        assert isinstance(loop, asyncio.SelectorEventLoop)
    finally:
        loop.close()

    calls = []
    monkeypatch.setattr(listen_sockets.uvicorn, "run", lambda app, **kw: calls.append(kw))
    listen_sockets.run_server(object(), "127.0.0.1", 3000)
    assert calls == [{"host": "127.0.0.1", "port": 3000, "loop": "app.services.listen_sockets:selector_loop_factory"}]

    served = {}
    class FakeServer:
        def __init__(self, config):
            served["config"] = config
        def run(self, sockets=None):
            served["sockets"] = sockets

    fake_v4 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    fake_v4.bind(("127.0.0.1", 0))
    try:
        monkeypatch.setattr(listen_sockets.uvicorn, "Server", FakeServer)
        monkeypatch.setattr(listen_sockets, "open_listen_sockets", lambda hosts, port: [fake_v4])
        listen_sockets.run_server(object(), "localhost", 0)
        assert served["config"].loop == "app.services.listen_sockets:selector_loop_factory"
    finally:
        fake_v4.close()


# --- Issue #209: batch heartbeats, slow-batch warning, ETA, summary, is_indexing ---

def test_209_batch_heartbeat_slow_warning_eta_and_summary(caplog):
    tracker = GitProgressTracker()
    tracker.jobs.clear()
    tracker.get_or_create_job(42, "demo-repo")
    items = [SimpleNamespace(rel_path="src/Small.cs", points=[object()] * 2), SimpleNamespace(rel_path="src/Huge.cs", points=[object()] * 15)]
    test_logger = logging.getLogger("test.issue209")
    with caplog.at_level(logging.INFO, logger="test.issue209"):
        mon = BatchProgressMonitor(
            repo_id=42, batch_index=3, total_batches=10, file_start=51, file_end=75,
            items=items, log=test_logger, tracker=tracker, heartbeat_interval=0.06, slow_batch_threshold=0.05,
        )
        time.sleep(0.14)
        mon.set_phase("vector_upsert")
        time.sleep(0.02)
        mon.finish()

    assert "Batch 3/10 (files 51-75): embedding 17 chunks" in caplog.text
    assert "Slow batch 3/10 (files 51-75)" in caplog.text
    assert "src/Huge.cs (15 chunks)" in caplog.text

    tracker.update_step(42, 4, "Ingested 10/100", current_file="src/Persisted.cs", processed=10, total=100)
    tracker.update_step(42, 4, "Parsed 45/100", current_file="src/ParsedAhead.cs", parsed_file="src/ParsedAhead.cs", parsed=45, total=100)
    snap = tracker.get_snapshot(42)
    assert snap["current_file"] == "src/Persisted.cs"
    assert snap["parsed_file"] == "src/ParsedAhead.cs"
    assert snap["parsed_files"] == 45 and snap["processed_files"] == 10 and snap["eta_seconds"] is not None

    assert format_duration(1023) == "17m03s" and compute_eta_seconds(50, 100, 10.0) == 10.0
    summary = format_sync_completion_summary(
        repo_name="demo", commit_sha="abcdef123456", total_seconds=1023, clone_seconds=67, ingest_seconds=955,
        chunks_embedded=10838, embedding_seconds=658, chunks_from_cache=76682, rate_limit_hits=0,
        added_count=0, modified_count=13168, deleted_count=0, total_vectors=87520, total_symbols=61778,
    )
    assert "Successfully synced repo 'demo' (@ abcdef12) in 17m03s" in summary and "76,682 from cache" in summary
    assert "Delta: +0 ~13168 -0. Vectors: 87520, Symbols: 61778" in summary
    tracker.jobs.clear()


def test_209_is_indexing_and_stats_true_during_repo_sync():
    import main as main_mod

    key, lock = _repo_sync_key(9991), _get_repo_lock(9991)
    assert lock.acquire(blocking=False)
    register_active_sync_repo(key, "large-csharp-repo")
    try:
        assert is_indexing() is True and "large-csharp-repo" in get_active_sync_repos()
        res = TestClient(main_mod.app).get("/admin/api/stats")
        assert res.status_code == 200 and res.json()["is_indexing"] is True and "large-csharp-repo" in res.json()["syncing_repos"]
    finally:
        unregister_active_sync_repo(key)
        lock.release()


# --- Issue #210: pgvector HNSW iterative scan, lexical-only flag, single-word routing ---

def test_210_pgvector_dense_query_enables_iterative_scan_and_falls_back_on_old_pgvector():
    stmts = []

    class FakeConn(_Ctx):
        def execute(self, stmt, params=None):
            stmts.append(str(stmt).strip())
            res = MagicMock()
            res.mappings.return_value.fetchall.return_value = [{"id": "1", "score": 0.88, "payload": {"rel_path": "Services/Product.cs"}}]
            return res

    rows = execute_pgvector_dense_query(
        conn=FakeConn(), table_name="vector_documents",
        where_clause="collection_name = :collection_name AND doc_type = :doc_type",
        params={"collection_name": "c", "doc_type": "code", "query_vec": "[0.1,0.2]"},
        target_limit=10, has_filter=True, is_pg_dialect=True,
    )
    assert len(rows) == 1
    assert any("SET LOCAL hnsw.iterative_scan = 'relaxed_order'" in s for s in stmts)
    assert any("SET LOCAL hnsw.ef_search = 40" in s for s in stmts)
    assert any("WITH relaxed_results AS MATERIALIZED" in s for s in stmts)

    old_stmts = []

    class OldPgConn(_Ctx):
        def execute(self, stmt, params=None):
            s = str(stmt).strip()
            old_stmts.append(s)
            if "hnsw.iterative_scan" in s:
                raise RuntimeError('unrecognized configuration parameter "hnsw.iterative_scan"')
            res = MagicMock()
            res.mappings.return_value.fetchall.return_value = []
            return res

    execute_pgvector_dense_query(
        conn=OldPgConn(), table_name="vector_documents",
        where_clause="collection_name = :collection_name AND doc_type = :doc_type",
        params={"collection_name": "c", "doc_type": "code", "query_vec": "[0.1,0.2]"},
        target_limit=10, has_filter=True, is_pg_dialect=True,
    )
    assert any("SET LOCAL hnsw.ef_search = 200" in s for s in old_stmts)


def test_210_hybrid_dense_empty_logs_warning_and_sets_flag(caplog):
    class FakeConn(_Ctx):
        def execute(self, stmt, params=None):
            res = MagicMock()
            if "ts_rank_cd" in str(stmt):
                res.mappings.return_value.fetchall.return_value = [
                    {"id": "lex-1", "sparse_score": 0.9, "payload": {"repo": "r", "rel_path": "a.cs", "doc_type": "code", "content": "class Foo {}"}}
                ]
            else:
                res.mappings.return_value.fetchall.return_value = []
            return res

    fake_engine = MagicMock()
    fake_engine.dialect.name = "postgresql"
    fake_engine.connect.side_effect = lambda: FakeConn()

    with caplog.at_level(logging.WARNING, logger="contextcortex.vector_store.pgvector"):
        hits = execute_pgvector_search(
            engine=fake_engine, table_name="vector_documents", collection_name="c",
            dimension=3, supported_modes=["hybrid", "semantic", "lexical"],
            embed_fn=lambda _q: [0.1, 0.2, 0.3], query_text="related products missing",
            doc_type="code", limit=5, search_mode="hybrid",
        )
    assert "dense leg returned 0 rows" in caplog.text and hits[0].payload.get("_dense_leg_empty") is True

    with patch("app.mcp.tools.execute_hybrid_search", return_value=hits):
        out = json.loads(asyncio.run(handle_search(query="related products missing", scope="code", mode="hybrid")))
    assert out["dense_fallback_lexical_only"] is True and "_dense_leg_empty" not in out["results"][0]


def test_210_single_word_routing_and_dense_fill():
    plan_padlock = classify_query_intent("padlock")
    assert plan_padlock.intent == "lexical_keywords"
    assert classify_query_intent("OrderProcessor").intent == "lexical_exact"
    assert classify_query_intent("helper_interval").intent == "lexical_exact"
    assert classify_query_intent('"padlock"').intent == "lexical_exact"

    track_a_hits = [
        VectorSearchResult(
            id="a1", score=0.92, dense_score=0.0, sparse_score=0.92,
            payload={"repo": "demo", "rel_path": "a.cs", "doc_type": "code", "symbol": "PadlockIcon", "content": "class PadlockIcon {}"},
        )
    ]
    assert should_early_return_lexical(plan_padlock, track_a_hits, doc_type="code") is False
    track_b_hits = [
        VectorSearchResult(
            id="b1", score=0.80, dense_score=0.80, sparse_score=0.0,
            payload={"repo": "demo", "rel_path": "b.cs", "doc_type": "code", "symbol": "SecurityLock", "content": "class SecurityLock {}"},
        )
    ]

    class FakeStore:
        mode = "postgres"
        def get_capabilities(self):
            return {"search_modes": ["hybrid", "semantic", "lexical"]}
        def search(self, **_kw):
            return track_b_hits

    with patch("app.services.search.get_vector_store", return_value=FakeStore()), \
         patch("app.services.search.run_fast_lexical_track", return_value=track_a_hits), \
         patch("app.services.search._enrich_code_ast_metadata"):
        fused = execute_hybrid_search("padlock", doc_type="code", limit=5, search_mode="hybrid")
    assert {r.payload["rel_path"] for r in fused} == {"a.cs", "b.cs"}


# --- Issue #211: indexed rel_path query + Track A batch hydration + tool guidance ---

def test_211_pgvector_file_chunks_uses_indexed_rel_path_first_and_batches(tmp_path, monkeypatch):
    engine = get_db_engine(f"sqlite:///{tmp_path / 'pg211.db'}", reset=True)
    store = PgVectorStore(engine=engine, collection_name="c211", dimension=3, auto_init=True)
    store.upsert_documents([
        VectorDocument(id="1", text="class Alpha {}", dense_vector=[1.0, 0.0, 0.0], repo="r1", doc_type="code", path="r1://src/Alpha.cs", rel_path="src/Alpha.cs", start_line=1, end_line=5),
        VectorDocument(id="2", text="class Beta {}", dense_vector=[0.0, 1.0, 0.0], repo="r1", doc_type="code", path="r1://src/Beta.cs", rel_path="src/Beta.cs", start_line=1, end_line=5),
    ])

    sql_seen = []
    orig_connect = engine.connect

    class SpyConn:
        def __init__(self, real):
            self._real = real
        def __enter__(self):
            self._real.__enter__()
            return self
        def __exit__(self, *a):
            return self._real.__exit__(*a)
        def execute(self, stmt, params=None):
            sql_seen.append(str(stmt))
            return self._real.execute(stmt, params)

    with patch.object(engine, "connect", side_effect=lambda: SpyConn(orig_connect())):
        chunks = execute_pgvector_file_chunks(engine, "vector_documents", "c211", "src/Alpha.cs", repo="r1")
    assert len(chunks) == 1 and len(sql_seen) == 1 and "REPLACE(" not in sql_seen[0] and "LIKE" not in sql_seen[0]

    sql_seen.clear()
    with patch.object(engine, "connect", side_effect=lambda: SpyConn(orig_connect())):
        batch = execute_pgvector_files_chunks_batch(engine, "vector_documents", "c211", [("r1", "src/Alpha.cs"), ("r1", "src/Beta.cs")])
    assert len(sql_seen) == 1 and len(batch[("r1", "src/Alpha.cs")]) == 1 and len(batch[("r1", "src/Beta.cs")]) == 1

    ast_db = tmp_path / "ast211.db"
    ast_url = f"sqlite:///{ast_db}"
    monkeypatch.setenv("DATABASE_URL", ast_url)
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", str(ast_db))
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", str(ast_db), raising=False)
    ast_engine = get_db_engine(ast_url, reset=True)
    init_db(engine=ast_engine)
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language) VALUES "
            "('r1', 'r1://src/Alpha.cs', 'AlphaOne', 'Alpha.AlphaOne', 'method', 1, 5, 'void AlphaOne()', 'c_sharp'),"
            "('r1', 'r1://src/Alpha.cs', 'AlphaTwo', 'Alpha.AlphaTwo', 'method', 1, 5, 'void AlphaTwo()', 'c_sharp'),"
            "('r1', 'r1://src/Beta.cs', 'AlphaBeta', 'Beta.AlphaBeta', 'method', 1, 5, 'void AlphaBeta()', 'c_sharp')"
        )
        conn.commit()

    batch_calls = []
    orig_batch = store.get_files_chunks_batch
    with patch.object(store, "get_files_chunks_batch", side_effect=lambda p: (batch_calls.append(list(p)), orig_batch(p))[1]), \
         patch.object(store, "get_file_chunks", side_effect=AssertionError("must use batch hydration")):
        hits = _query_ast_candidates(classify_query_intent("AlphaOne AlphaBeta"), [], {}, store, "r1", None, 10, True)
    assert len(batch_calls) == 1 and len(hits) == 3

    tool_desc = dict((name, desc) for name, _, desc in get_tool_definitions())["execute_script"]
    assert "search (~2-3 s)" not in tool_desc


# --- Issue #212: ^ and $ anchor to lines, not chunks, on pgvector/qdrant/chroma ---

def test_212_multiline_line_anchors_across_pgvector_qdrant_and_chroma(tmp_path):
    assert _translate_python_regex_for_postgres(r"^\s+private\b") == r"(?n)^\s+private\y"
    assert _translate_python_regex_for_postgres(r"(?i)^using System;$") == r"(?ni)^using System;$"
    assert _translate_python_regex_for_postgres(r"\Astart") == r"(?n)\Astart"

    chunk_text = "public class OrderBuilder\n{\n    private readonly Func<A, B> _getX = null;\n    public void Build() {}\n}"
    engine = get_db_engine(f"sqlite:///{tmp_path / 'pg212.db'}", reset=True)
    store = PgVectorStore(engine=engine, collection_name="c212", dimension=3, auto_init=True)
    store.upsert_documents([
        VectorDocument(
            id="doc1", text=chunk_text, dense_vector=[1.0, 0.0, 0.0],
            repo="r1", doc_type="code", path="r1://src/OrderBuilder.cs", rel_path="src/OrderBuilder.cs", start_line=12, end_line=16,
        )
    ])
    assert len(execute_pgvector_grep_chunks(engine, "vector_documents", "c212", r"^\s+private readonly Func<A, B> _getX", repo="r1", is_regex=True)) == 1
    assert len(execute_pgvector_grep_chunks(engine, "vector_documents", "c212", r"private readonly Func<A, B> _getX = null;$", repo="r1", is_regex=True)) == 1

    qdrant_client = MagicMock()
    qdrant_client.collection_exists.return_value = True
    qdrant_client.scroll.return_value = ([SimpleNamespace(payload={"repo": "r1", "rel_path": "src/OrderBuilder.cs", "content": chunk_text})], None)
    assert len(execute_qdrant_grep_chunks(qdrant_client, "c212", r"^\s+private", repo="r1", is_regex=True)) == 1
    assert len(execute_qdrant_grep_chunks(qdrant_client, "c212", r";$", repo="r1", is_regex=True)) == 1

    chroma_col = MagicMock()
    chroma_col.get.return_value = {"metadatas": [{"repo": "r1", "rel_path": "src/OrderBuilder.cs"}], "documents": [chunk_text]}
    assert len(execute_chroma_grep_chunks(chroma_col, r"^\s+private", repo="r1", is_regex=True)) == 1
    assert len(execute_chroma_grep_chunks(chroma_col, r";$", repo="r1", is_regex=True)) == 1
