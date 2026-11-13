import json
import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.chunking.symbol_extractor import extract_symbols_and_chunks
from app.services.database import get_db_connection, get_db_engine, init_db
from app.services.file_reader import FileReaderService, reset_file_reader_service
from app.services.indexing.git_delta_scanner import compute_git_repo_delta
from app.services.indexing.state import CODE_CHUNK_SIZE
from app.services.query_router import classify_query_intent, compute_token_coverage
from app.services.ripgrep_runner import find_ripgrep_binary, list_files_with_ripgrep
from app.services.search import execute_hybrid_search
from app.services.vector_store.base import VectorDocument
from app.services.vector_store.pgvector_store import PgVectorStore


def test_word_token_query_classification():
    """Verify word-token query classification across lexical_exact, agent keyword-series lexical_keywords, and semantic_prose."""
    # Exact symbols, quoted strings, paths, error codes
    for exact_q in (
        "helper_interval",
        "OrderProcessor.retry_payment",
        "CS0103",
        '"InvalidTokenError"',
        "app/services/search.py",
        "OrderProcessor retry_payment",
    ):
        plan = classify_query_intent(exact_q)
        assert plan.intent == "lexical_exact", f"Expected lexical_exact for {exact_q!r}, got {plan.intent}"

    # Agent keyword-series queries intended lexically
    for kw_q in (
        "order processor retry payment",
        "jwt bearer token validation",
        "rate limiter sliding window",
        "list customer orders",
        "health status check endpoint",
        "authenticate user credentials login",
    ):
        plan = classify_query_intent(kw_q)
        assert plan.intent == "lexical_keywords", f"Expected lexical_keywords for {kw_q!r}, got {plan.intent}"

    # Conceptual natural language queries intended semantically
    for sem_q in (
        "how does jwt refresh handle concurrency",
        "why does background indexing fail when a symlink is broken",
        "where is order payment retried?",
        "explain the architecture for retrying failed payments",
        "Overview of distributed services and vector databases",
    ):
        plan = classify_query_intent(sem_q)
        assert plan.intent == "semantic_prose", f"Expected semantic_prose for {sem_q!r}, got {plan.intent}"


def test_token_coverage_splits_camel_and_snake():
    """Verify CamelCase and snake_case decomposition yields full word-token coverage across symbol, path, and code content."""
    plan = classify_query_intent("order processor retry payment")
    score, meta = compute_token_coverage(
        plan.content_tokens,
        rel_path="services/order_processor.py",
        symbol="OrderProcessor.retry_payment",
        heading=None,
        content="class OrderProcessor:\n    def retry_payment(self, order_id: str) -> bool:\n        return True\n",
        raw_query=plan.raw_query,
    )
    assert meta["coverage"] == 1.0
    assert meta["matched_count"] == 4
    assert score >= 0.85


def test_ripgrep_grep_code_parity_pcre2_hidden_and_fallback(tmp_path, monkeypatch):
    """Verify default ripgrep scanning, broken symlink safety, PCRE2 lookarounds, hidden dotfiles, and Python fallback parity."""
    db_file = tmp_path / "rg_grep.db"
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", str(db_file))
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", str(db_file), raising=False)

    repo_dir = tmp_path / "repo"
    (repo_dir / "src").mkdir(parents=True)
    (repo_dir / ".github" / "workflows").mkdir(parents=True)
    (repo_dir / "node_modules" / "pkg").mkdir(parents=True)
    (repo_dir / ".venv").mkdir()
    os.symlink("/nonexistent/lib64", repo_dir / ".venv" / "lib64")

    (repo_dir / "src" / "payments.py").write_text("TOKEN_ALPHA = 1\nTOKEN_BETA = 2\n", encoding="utf-8")
    (repo_dir / ".github" / "workflows" / "ci.yml").write_text("name: TOKEN_ALPHA_CI\n", encoding="utf-8")
    (repo_dir / "node_modules" / "pkg" / "skip.py").write_text("TOKEN_ALPHA = 999\n", encoding="utf-8")
    (repo_dir / ".venv" / "skip.py").write_text("TOKEN_ALPHA = 888\n", encoding="utf-8")

    engine = get_db_engine(db_url, reset=True)
    init_db(engine=engine)
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO indexed_paths (path, type, recursive, enabled, category, repo) VALUES (?, 'directory', 1, 1, 'code', 'demo')",
            (str(repo_dir),),
        )
        conn.commit()
    reset_file_reader_service()
    reader = FileReaderService(storage_root=str(tmp_path / "storage"))

    if find_ripgrep_binary():
        rg_res = reader.grep_code(pattern="TOKEN_ALPHA", path_glob="*.py", context_lines=1)
        assert rg_res["total_matches"] == 1
        assert rg_res["matches"][0]["file"] == "src/payments.py"

        hidden_res = reader.grep_code(pattern="TOKEN_ALPHA_CI", context_lines=0)
        assert hidden_res["total_matches"] == 1
        assert hidden_res["matches"][0]["file"] == ".github/workflows/ci.yml"

        # Lookbehind triggers PCRE2 retry in rg
        pcre_res = reader.grep_code(pattern=r"(?<=TOKEN_)BETA", is_regex=True, context_lines=0)
        assert pcre_res["total_matches"] == 1
        assert pcre_res["matches"][0]["line"] == 2

    # Force pure-Python fallback and confirm parity
    monkeypatch.setenv("CONTEXTCORTEX_RG_PATH", "disabled")
    assert find_ripgrep_binary() is None
    py_res = reader.grep_code(pattern="TOKEN_ALPHA", path_glob="*.py", context_lines=1)
    assert py_res["total_matches"] == 1
    assert py_res["matches"][0]["file"] == "src/payments.py"


def test_ripgrep_file_discovery_and_delta_scanner_parity(tmp_path, monkeypatch):
    """Verify ripgrep --files discovery matches Python os.walk delta scanning while ignoring dotfiles and node_modules."""
    db_file = tmp_path / "delta.db"
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", str(db_file))
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", str(db_file), raising=False)
    engine = get_db_engine(db_url, reset=True)
    init_db(engine=engine)

    repo_dir = tmp_path / "checkout"
    (repo_dir / "app").mkdir(parents=True)
    (repo_dir / "node_modules").mkdir()
    (repo_dir / ".git").mkdir()
    (repo_dir / "app" / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (repo_dir / "app" / "app.min.js").write_text("var x=1;\n", encoding="utf-8")
    (repo_dir / "node_modules" / "dep.js").write_text("module.exports={};\n", encoding="utf-8")
    (repo_dir / ".secret.py").write_text("KEY='x'\n", encoding="utf-8")

    if find_ripgrep_binary():
        listed = list_files_with_ripgrep(str(repo_dir), ignored_dirs={"node_modules", ".git"}, include_hidden=False, extensions=(".py", ".js"))
        assert listed is not None
        rels = {rel for _, rel in listed}
        assert "app/main.py" in rels
        assert "node_modules/dep.js" not in rels
        assert ".secret.py" not in rels

    added_rg, _, _, _ = compute_git_repo_delta(str(repo_dir), "demo")
    monkeypatch.setenv("CONTEXTCORTEX_RG_PATH", "disabled")
    added_py, _, _, _ = compute_git_repo_delta(str(repo_dir), "demo")
    assert sorted(Path(p).name for p in added_rg) == ["main.py"]
    assert sorted(Path(p).name for p in added_py) == ["main.py"]


def test_parallel_early_return_beats_slow_embeddings_for_keyword_series(tmp_path, monkeypatch):
    """Verify exact queries make zero embedding calls and keyword-series queries return early from Track A without blocking on slow embeddings."""
    db_file = tmp_path / "router_perf.db"
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", str(db_file))
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", str(db_file), raising=False)

    engine = get_db_engine(db_url, reset=True)
    init_db(engine=engine)

    repo_dir = tmp_path / "orders_repo"
    (repo_dir / "services").mkdir(parents=True)
    order_file = repo_dir / "services" / "order_processor.py"
    order_code = (
        "class OrderProcessor:\n"
        "    def retry_payment(self, order_id: str, attempt: int) -> bool:\n"
        "        # Retry transient payment failures cleanly\n"
        "        return self._charge_gateway(order_id, attempt)\n"
    )
    order_file.write_text(order_code, encoding="utf-8")

    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO indexed_paths (path, type, recursive, enabled, category, repo) VALUES (?, 'directory', 1, 1, 'code', 'orders')",
            (str(repo_dir),),
        )
        conn.execute(
            """
            INSERT INTO ast_symbols (repo, filepath, name, full_symbol, kind, start_line, end_line, signature, language)
            VALUES ('orders', 'services/order_processor.py', 'retry_payment', 'OrderProcessor.retry_payment', 'function_definition', 2, 4, 'def retry_payment(self, order_id: str, attempt: int) -> bool:', 'python')
            """
        )
        conn.commit()

    embed_calls = []

    def slow_embed(text: str):
        embed_calls.append(text)
        time.sleep(0.55)
        if "transient" in text.lower() or "checkout" in text.lower() or "retry" in text.lower():
            return [1.0, 0.0, 0.0, 0.0]
        return [0.0, 1.0, 0.0, 0.0]

    store = PgVectorStore(engine=engine, collection_name="router_test", dimension=4)
    doc = VectorDocument(
        id="order-1",
        text=order_code,
        dense_vector=[1.0, 0.0, 0.0, 0.0],
        repo="orders",
        doc_type="code",
        language="python",
        path="services/order_processor.py",
        rel_path="services/order_processor.py",
        symbol="OrderProcessor.retry_payment",
        start_line=1,
        end_line=4,
    )
    assert store.upsert_documents([doc]) is True

    with patch("app.services.search.get_vector_store", return_value=store), \
         patch("app.services.vector_store.pgvector_store.get_dense_embedding", side_effect=slow_embed), \
         patch.object(store, "search", wraps=store.search) as spy_store_search:

        # 1. Exact query -> 0 embedding calls, instant return
        t0 = time.monotonic()
        exact_hits = execute_hybrid_search("OrderProcessor.retry_payment", doc_type="code", repo="orders")
        dt_exact = time.monotonic() - t0
        assert dt_exact < 0.25
        assert len(embed_calls) == 0
        assert len(exact_hits) >= 1
        assert exact_hits[0].payload.get("symbol") == "OrderProcessor.retry_payment"

        # 2. Agent keyword-series query -> parallel Track B started, Track A gates early return before slow embed finishes
        embed_calls.clear()
        t1 = time.monotonic()
        kw_hits = execute_hybrid_search("order processor retry payment", doc_type="code", repo="orders")
        dt_kw = time.monotonic() - t1
        assert dt_kw < 0.35, f"Expected early return before 0.55s embedding sleep, took {dt_kw:.3f}s"
        assert len(kw_hits) >= 1
        assert kw_hits[0].payload.get("rel_path") == "services/order_processor.py"
        assert "_lexical_meta" not in kw_hits[0].payload

        # Let background thread finish cleanly before semantic test
        time.sleep(0.6)

        # 3. Conceptual prose query -> awaits Track B semantic vector match
        embed_calls.clear()
        t2 = time.monotonic()
        sem_hits = execute_hybrid_search("how do we handle transient checkout failures?", doc_type="code", repo="orders")
        dt_sem = time.monotonic() - t2
        assert dt_sem >= 0.45
        assert len(embed_calls) >= 1
        assert len(sem_hits) >= 1
        assert spy_store_search.called


def test_ast_chunking_preserves_whole_functions_up_to_4000_chars():
    """Verify CODE_CHUNK_SIZE=4000 keeps complete functions and methods intact in a single AST chunk."""
    assert CODE_CHUNK_SIZE == 4000
    body_lines = ["    x = x + 1  # processing step in business workflow" for _ in range(42)]
    big_fn = "def process_large_workflow(x: int) -> int:\n" + "\n".join(body_lines) + "\n    return x\n"
    assert 1800 < len(big_fn) < 3500

    res = extract_symbols_and_chunks(big_fn, "workflow.py", repo="core")
    fn_chunks = [c for c in res.chunks if c.symbol == "process_large_workflow"]
    assert len(fn_chunks) == 1
    assert fn_chunks[0].start_line == 1
    assert fn_chunks[0].end_line == 44
