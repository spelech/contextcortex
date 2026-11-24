"""Regression tests for issues #215, #216, #217, and #218."""

import asyncio
import json
import os
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.mcp.handlers.diagnostic_handlers import handle_diagnose_issue
from app.mcp.handlers.file_handlers import handle_read_file
from app.mcp.handlers.grep_handlers import handle_grep_code
from app.mcp.handlers.search_handlers import handle_search
from app.services.chunking.tree_sitter_loader import detect_language, is_code_file
from app.services.database import get_db_connection, get_db_engine, init_db
from app.services.file_path_resolver import FilePathResolver
from app.services.file_reader import FileReaderService, reset_file_reader_service
from app.services.search import execute_hybrid_search
from app.services.search_ranking import cap_results_per_file, demote_trivial_code_results
from app.services.vector_store.base import VectorDocument, VectorSearchResult
from app.services.vector_store.pgvector_schema import ensure_pgvector_collection
from app.services.vector_store.pgvector_store import PgVectorStore


# ---------------------------------------------------------------------------
# Issue #215: CONCURRENTLY DDL must never run while any transaction is open,
# and INVALID indexes from interrupted builds must be dropped and rebuilt.
# ---------------------------------------------------------------------------

def test_215_concurrent_index_ddl_runs_with_zero_open_transactions_and_rebuilds_invalid_index():
    """Asserts active_tx == 0 during every CONCURRENTLY statement and INVALID indexes are rebuilt."""
    state = {"active_tx": 0, "sqls": [], "concurrent_tx_counts": [], "rebuilt_invalid": False}

    class FakeTx:
        def __enter__(self):
            state["active_tx"] += 1
            return self

        def __exit__(self, *a):
            state["active_tx"] -= 1
            return False

    class FakeConn:
        def __init__(self, autocommit: bool = False):
            self._autocommit = autocommit
            self._implicit_tx = False

        def __enter__(self):
            return self

        def __exit__(self, *a):
            if self._implicit_tx:
                state["active_tx"] -= 1
                self._implicit_tx = False
            return False

        def begin(self):
            return FakeTx()

        def rollback(self):
            if self._implicit_tx:
                state["active_tx"] -= 1
                self._implicit_tx = False

        def execution_options(self, **kw):
            return FakeConn(autocommit=(kw.get("isolation_level") == "AUTOCOMMIT"))

        def execute(self, stmt, params=None):
            s = str(stmt).strip()
            state["sqls"].append(s)
            if "CONCURRENTLY" in s.upper():
                assert self._autocommit, f"CONCURRENTLY must run in AUTOCOMMIT: {s}"
                state["concurrent_tx_counts"].append(state["active_tx"])
                assert state["active_tx"] == 0, f"Open transaction held during CONCURRENTLY DDL: {s}"
                if "DROP INDEX CONCURRENTLY" in s.upper() and "idx_vector_documents_coll_repo_rel_path" in s:
                    state["rebuilt_invalid"] = True
            elif not self._autocommit and state["active_tx"] == 0 and not self._implicit_tx:
                # SQLAlchemy starts an implicit DBAPI transaction on first SELECT if not autocommit
                self._implicit_tx = True
                state["active_tx"] += 1

            res = MagicMock()
            res.fetchone.return_value = (1536,) if "SELECT atttypmod" in s else None
            res.fetchall.return_value = [("collection_name",), ("id",)] if "i.indisprimary" in s else []
            if "FROM pg_extension" in s or "attname = 'collection_name'" in s or "attname = 'fts'" in s:
                res.scalar.return_value = 1
            elif "SELECT EXISTS (SELECT 1 FROM" in s:
                res.scalar.return_value = True
            elif "FROM pg_indexes" in s:
                idx = (params or {}).get("idx", "")
                if idx == "idx_vector_documents_coll_repo_rel_path":
                    # Simulate an INVALID index left behind by an interrupted CONCURRENTLY build
                    res.fetchone.return_value = ("CREATE INDEX idx_vector_documents_coll_repo_rel_path ON vector_documents (collection_name, repo, rel_path)", False)
                else:
                    res.fetchone.return_value = ("CREATE INDEX ...", True)
            return res

    fake_engine = MagicMock()
    fake_engine.dialect.name = "postgresql"
    fake_engine.connect.side_effect = lambda: FakeConn()

    assert ensure_pgvector_collection(fake_engine, "vector_documents", 1536) is True
    assert state["concurrent_tx_counts"], "Expected at least one CONCURRENTLY DDL statement"
    assert all(c == 0 for c in state["concurrent_tx_counts"])
    assert state["rebuilt_invalid"] is True
    assert any("CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_vector_documents_coll_repo_rel_path" in s for s in state["sqls"])


@pytest.mark.skipif(not os.getenv("TEST_POSTGRES_URL"), reason="Requires TEST_POSTGRES_URL pointing to a real PostgreSQL + pgvector database")
def test_215_real_postgres_concurrent_index_migration_no_deadlock():
    """Integration test against real Postgres: populated table + missing file-lookup index completes cleanly."""
    from sqlalchemy import text

    engine = get_db_engine(os.environ["TEST_POSTGRES_URL"], reset=True)
    table = "vector_documents_test_215"
    try:
        assert ensure_pgvector_collection(engine, table, 4) is True
        store = PgVectorStore(engine=engine, table_name=table, collection_name="t215", dimension=4, auto_init=False)
        store.upsert_documents([
            VectorDocument(id=f"d{i}", text=f"class C{i} {{}}", dense_vector=[0.1, 0.2, 0.3, 0.4], repo="r", doc_type="code", path=f"r://f{i}.cs", rel_path=f"f{i}.cs")
            for i in range(5)
        ])
        with engine.connect() as conn, conn.begin():
            conn.execute(text(f"DROP INDEX IF EXISTS idx_{table}_coll_repo_rel_path"))
        t0 = time.monotonic()
        assert ensure_pgvector_collection(engine, table, 4) is True
        assert time.monotonic() - t0 < 15.0
    finally:
        with engine.connect() as conn, conn.begin():
            conn.execute(text(f"DROP TABLE IF EXISTS {table}"))


# ---------------------------------------------------------------------------
# Issue #216: HTML test-data pages not indexed as code + per-file result cap
# ---------------------------------------------------------------------------

def test_216_html_classified_as_doc_and_code_search_caps_per_file_in_all_modes():
    assert detect_language("UnitTests/TestData/inputs/products_x.html") == "html"
    assert detect_language("UnitTests/TestData/inputs/page.htm") == "html"
    assert is_code_file("UnitTests/TestData/inputs/products_x.html") is False
    assert is_code_file("UnitTests/TestData/inputs/page.htm") is False
    assert is_code_file("Services/ProductService.cs") is True

    def _hit(hid: str, path: str, score: float, lang: str = "html", start_line: int = 1):
        return VectorSearchResult(
            id=hid, score=score, dense_score=score, sparse_score=0.0,
            payload={
                "repo": "shop", "rel_path": path, "doc_type": "code", "language": lang,
                "start_line": start_line, "end_line": start_line + 10,
                "content": f"chunk {hid} product related items",
            },
        )

    # 5 chunks from one HTML test-data file + 3 real C# files with slightly lower raw dense scores
    raw_hits = [
        _hit(f"html-{i}", "UnitTests/TestData/inputs/products_widget.html", 0.495 - i * 0.001, "html", start_line=(i + 1) * 30)
        for i in range(5)
    ] + [
        _hit("cs-1", "Services/RelatedProductsService.cs", 0.43, "c_sharp", start_line=10),
        _hit("cs-2", "Controllers/ProductController.cs", 0.41, "c_sharp", start_line=10),
        _hit("cs-3", "Repositories/ProductRepository.cs", 0.39, "c_sharp", start_line=10),
    ]

    demoted = demote_trivial_code_results(list(raw_hits), query_text="related products missing from product page", doc_type="code")
    capped = cap_results_per_file(demoted, limit=5, max_per_file=2)
    assert [r.id for r in capped[:3]] == ["cs-1", "cs-2", "cs-3"]
    html_count = sum(1 for r in capped if r.payload["rel_path"].endswith(".html"))
    assert html_count <= 2

    # Verify execute_hybrid_search enforces per-file cap and HTML/TestData demotion in semantic, lexical, and hybrid modes
    class FakeStore:
        mode = "postgres"

        def get_capabilities(self):
            return {"search_modes": ["hybrid", "semantic", "lexical"]}

        def search(self, **_kw):
            return [
                _hit(f"h-{i}", "UnitTests/TestData/inputs/products_widget.html", 0.50 - i * 0.001, "html", start_line=(i + 1) * 30)
                for i in range(5)
            ] + [
                _hit("cs-1", "Services/RelatedProductsService.cs", 0.42, "c_sharp", start_line=10),
                _hit("cs-2", "Controllers/ProductController.cs", 0.40, "c_sharp", start_line=10),
                _hit("cs-3", "Repositories/ProductRepository.cs", 0.38, "c_sharp", start_line=10),
            ]

    with patch("app.services.search.get_vector_store", return_value=FakeStore()), \
         patch("app.services.search.run_fast_lexical_track", return_value=[]), \
         patch("app.services.search._enrich_code_ast_metadata"):
        for mode in ("semantic", "lexical", "hybrid"):
            res = execute_hybrid_search("related products missing from the product page", doc_type="code", limit=5, search_mode=mode)
            assert len(res) == 5
            assert res[0].payload["rel_path"] == "Services/RelatedProductsService.cs", f"Expected C# first in {mode} mode"
            per_file = {}
            for r in res:
                per_file[r.payload["rel_path"]] = per_file.get(r.payload["rel_path"], 0) + 1
            assert max(per_file.values()) <= 2, f"Expected <=2 results per file in {mode} mode, got {per_file}"


# ---------------------------------------------------------------------------
# Issue #217: async MCP & API handlers must run blocking work in worker threads
# ---------------------------------------------------------------------------

def test_217_concurrent_mcp_tool_calls_run_in_parallel_not_serialized():
    """8 parallel handle_search calls sleeping 0.25s each must complete in ~0.3-0.8s, not ~2.0s."""
    def _slow_search(**_kw):
        time.sleep(0.25)
        return [
            VectorSearchResult(
                id="1", score=0.9, dense_score=0.9, sparse_score=0.0,
                payload={"repo": "r", "rel_path": "a.py", "doc_type": "code", "start_line": 1, "end_line": 2, "content": "def a(): pass"},
            )
        ]

    async def _run_8_searches():
        t0 = time.perf_counter()
        outs = await asyncio.gather(*(handle_search(query=f"query {i}", scope="code") for i in range(8)))
        return time.perf_counter() - t0, outs

    with patch("app.mcp.tools.execute_hybrid_search", side_effect=_slow_search), \
         patch("app.mcp.handlers.search_handlers.get_active_sync_status", return_value=None):
        elapsed, outputs = asyncio.run(_run_8_searches())

    assert len(outputs) == 8
    assert all(json.loads(o)["returned"] == 1 for o in outputs)
    assert elapsed < 1.2, f"8 concurrent searches appeared serialized on event loop (took {elapsed:.2f}s)"

    # Also verify grep_code, read_file, and diagnose_issue overlap in parallel
    fake_reader = MagicMock()
    fake_reader.grep_code.side_effect = lambda **_kw: (time.sleep(0.25), {"matches": []})[1]
    fake_reader.read_file.side_effect = lambda **_kw: (time.sleep(0.25), {"filepath": "a.py", "content": "x=1", "start_line": 1, "end_line": 1, "total_lines": 1})[1]

    async def _run_mixed():
        t0 = time.perf_counter()
        res = await asyncio.gather(
            handle_grep_code(pattern="foo"),
            handle_read_file(path="a.py"),
            handle_diagnose_issue(issue_text="NullReferenceException in Foo.Bar"),
        )
        return time.perf_counter() - t0, res

    with patch("app.mcp.handlers.grep_handlers._resolve_reader_factory", return_value=lambda: fake_reader), \
         patch("app.mcp.handlers.file_handlers._get_tools_attr", return_value=lambda: fake_reader), \
         patch("app.mcp.handlers.diagnostic_handlers._get_tools_attr", return_value=lambda **_kw: (time.sleep(0.25), {"call_chain": {"steps": []}})[1]), \
         patch("app.mcp.handlers.grep_handlers.get_active_sync_status", return_value=None), \
         patch("app.mcp.handlers.diagnostic_handlers.get_active_sync_status", return_value=None):
        mixed_elapsed, _ = asyncio.run(_run_mixed())
    assert mixed_elapsed < 0.65, f"Mixed MCP tool calls appeared serialized (took {mixed_elapsed:.2f}s)"


# ---------------------------------------------------------------------------
# Issue #218: unique partial suffix auto-resolves; ambiguous suffixes rank first
# ---------------------------------------------------------------------------

def test_218_read_file_resolves_unique_suffix_and_ranks_ambiguous_suffixes_first(tmp_path, monkeypatch):
    db_file = tmp_path / "suffix218.db"
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", str(db_file))
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", str(db_file), raising=False)

    engine = get_db_engine(db_url, reset=True)
    init_db(engine=engine)
    store = PgVectorStore(engine=engine, collection_name="c218", dimension=3, auto_init=True)
    store.upsert_documents([
        VectorDocument(
            id="api-target", text="namespace MyProject;\npublic class API { public int Ok() => 1; }",
            dense_vector=[1.0, 0.0, 0.0], repo="shop", doc_type="code",
            path="shop://Area/Source/MyProject/API.cs", rel_path="Area/Source/MyProject/API.cs",
            start_line=1, end_line=2,
        ),
    ])

    with get_db_connection() as conn:
        conn.execute("INSERT INTO git_repositories (name, url, branch, status) VALUES ('shop', 'https://example.com/shop.git', 'main', 'synced')")
        for rel in (
            "Area/Source/MyProject/API.cs",
            "Other/Source/OtherProject/API.cs",
            "Other/Source/APIVersion.cs",
            "Other/Source/APIException.cs",
            "Other/Source/ApiXmlSerializer.cs",
        ):
            conn.execute(
                "INSERT INTO indexed_files (filepath, repo, doc_type, language, mtime) VALUES (?, 'shop', 'code', 'c_sharp', 0)",
                (f"shop://{rel}",),
            )
        conn.commit()

    reset_file_reader_service()
    reader = FileReaderService(storage_root=str(tmp_path / "storage"))

    # 1. Unique suffix "MyProject/API.cs" auto-resolves and reports resolved_from
    with patch("app.services.vector_store.get_vector_store", return_value=store), \
         patch("app.mcp.handlers.file_handlers._get_tools_attr", return_value=lambda: reader):
        out = json.loads(asyncio.run(handle_read_file(path="MyProject/API.cs", repo="shop")))
    assert out["file"] == "Area/Source/MyProject/API.cs"
    assert out["resolved_from"] == "MyProject/API.cs"
    assert "public class API" in out["content"]

    # 2. Ambiguous suffix: add a second file ending with /MyProject/API.cs -> both must appear first in suggestions
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO indexed_files (filepath, repo, doc_type, language, mtime) VALUES (?, 'shop', 'code', 'c_sharp', 0)",
            ("shop://Backup/Source/MyProject/API.cs",),
        )
        conn.commit()

    with patch("app.services.vector_store.get_vector_store", return_value=store), \
         patch("app.mcp.handlers.file_handlers._get_tools_attr", return_value=lambda: reader):
        err_out = json.loads(asyncio.run(handle_read_file(path="MyProject/API.cs", repo="shop")))
    assert "error" in err_out
    assert "Area/Source/MyProject/API.cs" in err_out["error"]
    assert "Backup/Source/MyProject/API.cs" in err_out["error"]
    assert err_out["error"].index("Area/Source/MyProject/API.cs") < err_out["error"].index("Backup/Source/MyProject/API.cs")

    # 3. Trailing path segment count ranks closer suffix matches ahead of basename-only matches
    resolver = FilePathResolver(db_conn_factory=lambda: get_db_connection())
    sugs = resolver.suggest_similar_indexed_files("Source/MyProject/API.cs", "shop", limit=5)
    assert sugs[:2] == ["Area/Source/MyProject/API.cs", "Backup/Source/MyProject/API.cs"]
