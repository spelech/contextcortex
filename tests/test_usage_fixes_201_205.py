"""Regression tests for Issues #201, #202, #203, #204, and #205."""

import asyncio
import json
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.dialects import postgresql

import app.services.database as db_service
from app.mcp.handlers.file_handlers import handle_read_file
from app.mcp.handlers.grep_handlers import handle_grep_code
from app.mcp.handlers.search_handlers import handle_search
from app.services.chunking.symbol_extractor import extract_symbols_and_chunks
from app.services.chunking.tree_sitter_loader import get_tree_sitter_parser
from app.services.code_grep_chunks import path_matches_filter
from app.services.code_grep_scanner import looks_like_regex
from app.services.database.engine import get_db_engine, init_db
from app.services.file_reader import FileReaderService
from app.services.indexing.processor import process_file_content
from app.services.search import execute_hybrid_search
from app.services.search_ranking import demote_trivial_code_results, is_substantive_code_fragment
from app.services.vector_store.base import VectorDocument, VectorSearchResult
from app.services.vector_store.chroma_queries import execute_chroma_grep_chunks
from app.services.vector_store.pgvector_chunk_scanner import (
    _translate_python_regex_for_postgres,
    execute_pgvector_grep_chunks,
)
from app.services.vector_store.pgvector_store import PgVectorStore
from app.services.vector_store.qdrant_queries import execute_qdrant_grep_chunks

needs_csharp = pytest.mark.skipif(get_tree_sitter_parser("c_sharp") is None, reason="needs C# tree-sitter grammar")


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    db_file = tmp_path / "usage_201_205.db"
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("CACHE_DB_PATH", str(db_file))
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", str(db_file))
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", str(db_file), raising=False)
    init_db(engine=get_db_engine(db_url, reset=True))
    return tmp_path


def _make_sqlite_pgvector_store():
    engine = create_engine("sqlite:///:memory:")
    store = PgVectorStore(engine=engine, collection_name="c202", dimension=4, auto_init=True)
    return store


# --- Issue #201: guessed read_file path error & shorter-stem suggestions ---


def test_201_guessed_path_suggests_shorter_stem_and_omits_not_indexed(isolated_db, monkeypatch):
    empty_clones = isolated_db / "empty_clones"
    empty_clones.mkdir()
    monkeypatch.setattr("app.services.git_manager.PERSISTENT_REPOS_DIR", str(empty_clones))

    with db_service.get_db_connection() as conn:
        conn.execute(
            "INSERT INTO git_repositories (name, url, branch, status, enabled, keep_shallow) "
            "VALUES ('shop', 'https://example.com/s.git', 'main', 'synced', 1, 0)"
        )
        conn.execute(
            "INSERT INTO indexed_files (filepath, repo, doc_type, language) VALUES "
            "('shop://Queries/FooItemQuery.cs', 'shop', 'code', 'c_sharp'), "
            "('shop://QueryResolvers/OtherQueryResolver.cs', 'shop', 'code', 'c_sharp')"
        )
        conn.commit()

    reader = FileReaderService(storage_root=str(isolated_db / "storage"))
    fake_store = MagicMock()
    fake_store.get_file_chunks.return_value = []

    with patch("app.services.vector_store.get_vector_store", return_value=fake_store):
        with pytest.raises(FileNotFoundError) as exc:
            reader.read_file("QueryResolvers/FooItemQueryResolver.cs", repo="shop")

    msg = str(exc.value)
    assert "(not indexed)" not in msg
    assert "No indexed file has this path" in msg
    assert "Queries/FooItemQuery.cs" in msg
    assert "find_symbol" in msg


# --- Issue #202: pgvector/qdrant/chroma grep_code path filter, folder filter, regex dialect & fallback ---


def test_202_pgvector_grep_applies_path_filter_before_sql_limit():
    store = _make_sqlite_pgvector_store()
    docs = [
        VectorDocument(
            id=f"other-{i}",
            text=f"public class Other{i} {{ public void Run() {{}} }}",
            dense_vector=[0.1, 0.2, 0.3, 0.4],
            repo="shop",
            doc_type="code",
            path=f"shop://Other/Other{i}.cs",
            rel_path=f"Other/Other{i}.cs",
            start_line=1,
            end_line=1,
        )
        for i in range(260)
    ]
    docs.append(
        VectorDocument(
            id="target-factory",
            text="public class SomeFactory { public Product Build() => null; }",
            dense_vector=[0.1, 0.2, 0.3, 0.4],
            repo="shop",
            doc_type="code",
            path="shop://Source/Some.Project/SomeFactory.cs",
            rel_path="Source/Some.Project/SomeFactory.cs",
            start_line=1,
            end_line=1,
        )
    )
    assert store.upsert_documents(docs) is True

    # Glob filter must find SomeFactory.cs even though >250 other rows match "public"
    hits = store.grep_chunks(pattern="public", repo="shop", path_glob="*SomeFactory.cs", limit=10)
    assert len(hits) == 1
    assert hits[0]["rel_path"] == "Source/Some.Project/SomeFactory.cs"

    # Folder filter without wildcards must also match files inside the folder
    folder_hits = store.grep_chunks(pattern="Build", repo="shop", path_glob="Source/Some.Project", limit=10)
    assert len(folder_hits) == 1
    assert folder_hits[0]["rel_path"] == "Source/Some.Project/SomeFactory.cs"


def test_202_folder_filter_works_across_qdrant_and_chroma_chunk_scanners():
    assert path_matches_filter("Source/Some.Project/SomeFactory.cs", "Source/Some.Project") is True
    assert path_matches_filter("Other/SomeFactory.cs", "Source/Some.Project") is False

    # Qdrant chunk scanner
    q_client = MagicMock()
    q_client.collection_exists.return_value = True
    q_client.scroll.return_value = (
        [
            SimpleNamespace(payload={"repo": "shop", "rel_path": "Source/Some.Project/A.cs", "content": "FindMe()"}),
            SimpleNamespace(payload={"repo": "shop", "rel_path": "Other/B.cs", "content": "FindMe()"}),
        ],
        None,
    )
    q_hits = execute_qdrant_grep_chunks(q_client, "coll", "FindMe", repo="shop", path_glob="Source/Some.Project")
    assert [h["rel_path"] for h in q_hits] == ["Source/Some.Project/A.cs"]

    # Chroma chunk scanner
    c_coll = MagicMock()
    c_coll.get.return_value = {
        "metadatas": [
            {"repo": "shop", "rel_path": "Source/Some.Project/A.cs", "content": "FindMe()"},
            {"repo": "shop", "rel_path": "Other/B.cs", "content": "FindMe()"},
        ],
        "documents": ["FindMe()", "FindMe()"],
    }
    c_hits = execute_chroma_grep_chunks(c_coll, "FindMe", repo="shop", path_glob="Source/Some.Project")
    assert [h["rel_path"] for h in c_hits] == ["Source/Some.Project/A.cs"]


def test_202_postgres_regex_word_boundary_translation_and_escaped_punct_fallback():
    assert _translate_python_regex_for_postgres(r"SomeQuery\b") == r"(?n)SomeQuery\y"
    assert _translate_python_regex_for_postgres(r"[\b]foo\B") == r"(?n)[\b]foo\Y"
    assert _translate_python_regex_for_postgres(r"(?P<name>Foo)\b") == r"(?n)(?:Foo)\y"

    # End-to-end word boundary match on pgvector grep_chunks
    store = _make_sqlite_pgvector_store()
    store.upsert_documents([
        VectorDocument(id="1", text="var x = new SomeQuery();", dense_vector=[0.1] * 4, repo="shop", doc_type="code", path="shop://A.cs", rel_path="A.cs", start_line=1, end_line=1),
        VectorDocument(id="2", text="var y = new SomeQueryResolver();", dense_vector=[0.1] * 4, repo="shop", doc_type="code", path="shop://B.cs", rel_path="B.cs", start_line=1, end_line=1),
    ])
    hits = store.grep_chunks(pattern=r"SomeQuery\b", repo="shop", is_regex=True)
    assert [h["rel_path"] for h in hits] == ["A.cs"]

    # Escaped punctuation triggers regex fallback in handle_grep_code
    assert looks_like_regex(r"GetValue\(") is True
    assert looks_like_regex(r"C:\folder\file") is False

    fake_reader = MagicMock()
    fake_reader.grep_code.side_effect = [
        {"matches": []},
        {"matches": [{"repo": "shop", "file": "A.cs", "line": 5, "match_text": "var v = GetValue(1);", "context": []}]},
    ]
    with patch("app.mcp.handlers.grep_handlers._resolve_reader_factory", return_value=lambda: fake_reader):
        payload = json.loads(asyncio.run(handle_grep_code(pattern=r"GetValue\(", repo="shop")))
    assert payload["total_matches"] == 1
    assert "regex" in payload.get("pattern_mode", "")


# --- Issue #203: file header chunks, preserved symbol indent, and missing_lines reporting ---


@needs_csharp
def test_203_csharp_header_chunks_and_preserved_indent_roundtrip(isolated_db):
    source = (
        "using System;\n"
        "using Acme.Catalog;\n"
        "\n"
        "namespace Acme.Store.Factories\n"
        "{\n"
        "    public class SomeFactory : ISomeFactory\n"
        "    {\n"
        "        public IRelatedProductRetriever Build(\n"
        "            BlueprintId blueprintId)\n"
        "        {\n"
        "            return new RelatedProductRetriever(blueprintId);\n"
        "        }\n"
        "    }\n"
        "}\n"
    )
    res = extract_symbols_and_chunks(source, "Factories/SomeFactory.cs", repo="shop")
    headers = [c for c in res.chunks if c.kind == "file_header"]
    assert headers and "using Acme.Catalog;" in headers[0].content
    assert "namespace Acme.Store.Factories" in headers[0].content

    build_chunks = [c for c in res.chunks if c.symbol and c.symbol.endswith(".Build")]
    assert build_chunks and build_chunks[0].content.startswith("        public IRelatedProductRetriever Build(")

    # Processor must preserve horizontal indent on VectorDocument.text
    with patch("app.services.indexing.processor.get_hybrid_embeddings_batch", side_effect=lambda texts: [{"dense": [0.1] * 4, "sparse": None} for _ in texts]):
        pts, _, _, _, _, _ = process_file_content(
            filepath="shop://Factories/SomeFactory.cs",
            rel_path="Factories/SomeFactory.cs",
            content=source,
            repo="shop",
            doc_type="code",
        )
    store = _make_sqlite_pgvector_store()
    assert store.upsert_documents(pts) is True

    # grep_code / chunk grep finds `using` line
    using_hits = store.grep_chunks(pattern="using Acme.Catalog;", repo="shop")
    assert len(using_hits) == 1

    # read_file from chunks reconstructs header + 8-space indent on Build()
    reader = FileReaderService(storage_root=str(isolated_db / "storage"))
    with patch("app.services.vector_store.get_vector_store", return_value=store):
        rebuilt = reader.read_file("shop://Factories/SomeFactory.cs")
    assert "using Acme.Catalog;" in rebuilt["content"]
    assert "        public IRelatedProductRetriever Build(" in rebuilt["content"]
    assert "missing_lines" not in rebuilt


def test_203_read_file_reports_missing_lines_when_header_chunks_absent(isolated_db):
    fake_store = MagicMock()
    fake_store.get_file_chunks.return_value = [
        {"start_line": 12, "end_line": 14, "content": "class SomeFactory\n{\n}"},
    ]
    reader = FileReaderService(storage_root=str(isolated_db / "storage"))
    with patch("app.mcp.handlers.file_handlers.get_file_reader_service", return_value=reader), \
         patch("app.services.vector_store.get_vector_store", return_value=fake_store):
        payload = json.loads(asyncio.run(handle_read_file(path="shop://SomeFactory.cs")))
    assert payload["source"] == "vector_store"
    assert payload["missing_lines"] == [[1, 11]]


# --- Issue #204: tiny tail fragments demoted/skipped & search total <= limit ---


@needs_csharp
def test_204_tail_endregion_fragments_not_emitted_and_demoted_at_query_time():
    assert is_substantive_code_fragment("#endregion\n    }") is False
    assert is_substantive_code_fragment("    }\n}") is False
    assert is_substantive_code_fragment("public int Count() => 1;") is True

    source = (
        "public class CatalogService\n"
        "{\n"
        "    #region Methods\n"
        "    public void Refresh() { }\n"
        "    #endregion\n"
        "}\n"
    )
    res = extract_symbols_and_chunks(source, "CatalogService.cs", repo="shop")
    for ch in res.chunks:
        assert is_substantive_code_fragment(ch.content), f"Non-substantive fragment emitted: {ch.content!r}"

    # Query-time demotion even on legacy already-indexed fragments
    frag = VectorSearchResult(
        id="frag-1", score=0.3826, dense_score=0.3826, sparse_score=0.0,
        payload={"doc_type": "code", "language": "c_sharp", "rel_path": "A.cs", "content": "#endregion\n    }"},
    )
    real = VectorSearchResult(
        id="real-1", score=0.3200, dense_score=0.3200, sparse_score=0.0,
        payload={"doc_type": "code", "language": "c_sharp", "rel_path": "B.cs", "content": "public List<Item> FilterItems() => items;"},
    )
    ranked = demote_trivial_code_results([frag, real])
    assert ranked[0].id == "real-1"
    assert ranked[1].score < 0.05


def test_204_search_total_and_returned_never_exceed_limit():
    # Simulate 4 hits returned for fetch_limit = limit(3) + 1
    hits = [
        VectorSearchResult(
            id=f"h-{i}", score=0.9 - i * 0.1,
            payload={"repo": "shop", "rel_path": f"File{i}.cs", "doc_type": "code", "content": f"public void M{i}() {{}}"},
        )
        for i in range(4)
    ]
    with patch("app.mcp.handlers.search_handlers._get_tools_attr", return_value=lambda **kw: hits):
        payload = json.loads(asyncio.run(handle_search(query="filter", repo="shop", limit=3)))
    assert len(payload["results"]) == 3
    assert payload["returned"] == 3
    assert payload["total"] == 3
    assert payload["has_more"] is True
    assert payload["next_offset"] == 3


# --- Issue #205: pgvector stored generated fts column, migration, and query SQL ---


def test_205_pgvector_uses_stored_fts_column_and_migrates_legacy_index(caplog):
    mock_engine = MagicMock()
    mock_engine.dialect = postgresql.dialect()
    ddl_seen = []

    def _exec_ddl(stmt, params=None):
        s = str(stmt)
        ddl_seen.append(s)
        res = MagicMock()
        res.fetchone.return_value = None
        res.fetchall.return_value = [("collection_name",), ("id",)]
        if "FROM pg_extension" in s:
            res.scalar.return_value = 1
        elif "SELECT EXISTS" in s:
            res.scalar.return_value = False
        elif "attname = 'collection_name'" in s:
            res.scalar.return_value = 1
        elif "attname = 'fts'" in s:
            res.scalar.return_value = None
        elif "FROM pg_indexes" in s and (params or {}).get("idx") == "idx_vector_documents_fts":
            res.scalar.return_value = "CREATE INDEX idx_vector_documents_fts ON public.vector_documents USING gin (to_tsvector('simple', content))"
        else:
            res.scalar.return_value = None
        return res

    mock_conn = MagicMock()
    mock_conn.execute.side_effect = _exec_ddl
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    store = PgVectorStore(engine=mock_engine, dimension=4, auto_init=False)
    assert store.ensure_collection() is True
    ddl_sql = " ".join(ddl_seen)
    assert "fts tsvector GENERATED ALWAYS AS" in ddl_sql
    assert "ADD COLUMN IF NOT EXISTS fts tsvector GENERATED ALWAYS AS" in ddl_sql
    assert "DROP INDEX IF EXISTS idx_vector_documents_fts" in ddl_sql
    assert "USING gin (fts)" in ddl_sql

    # Verify lexical & hybrid queries use stored `fts` column instead of recomputing to_tsvector
    search_sqls = []

    def _exec_search(stmt, params=None):
        s = str(stmt)
        search_sqls.append(s)
        res = MagicMock()
        if "ts_rank_cd" in s:
            res.mappings.return_value.fetchall.return_value = [
                {"id": "d1", "sparse_score": 0.5, "payload": {"content": "public void ApplyFilter() {}", "doc_type": "code"}},
            ]
        else:
            res.mappings.return_value.fetchall.return_value = [
                {"id": "d1", "score": 0.7, "payload": {"content": "public void ApplyFilter() {}", "doc_type": "code"}},
            ]
        return res

    mock_conn.execute.side_effect = _exec_search

    with caplog.at_level(logging.DEBUG, logger="contextcortex.vector_store.pgvector"), \
         patch("app.services.vector_store.pgvector_store.get_dense_embedding", return_value=[0.1, 0.2, 0.3, 0.4]):
        results = store.search(query_text="apply filter", search_mode="hybrid", limit=5)

    assert len(results) == 1
    lex_sql = next(s for s in search_sqls if "ts_rank_cd" in s)
    assert "ts_rank_cd(fts," in lex_sql
    assert "fts @@" in lex_sql
    assert "to_tsvector(" not in lex_sql
    assert any("pgvector hybrid legs:" in rec.message for rec in caplog.records)
