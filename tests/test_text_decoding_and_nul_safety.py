"""Tests for source text decoding (UTF-8/16/32) and NUL-safe, failure-isolated PgVectorStore upserts."""

import codecs
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, text

from app.services.text_decoding import decode_source_bytes, read_source_text, strip_nul
from app.services.vector_store.base import VectorDocument

SAMPLE = "SELECT name FROM dbo.Accounts -- Größe\r\nrequests==2.32.3\r\n"


@pytest.fixture(autouse=True)
def embedding_dimension():
    with patch("app.services.vector_store.pgvector_store.get_dense_dim", return_value=4):
        yield


@pytest.mark.parametrize(
    "raw",
    [
        codecs.BOM_UTF16_LE + SAMPLE.encode("utf-16-le"),
        codecs.BOM_UTF16_BE + SAMPLE.encode("utf-16-be"),
        SAMPLE.encode("utf-16-le"),
        SAMPLE.encode("utf-16-be"),
        codecs.BOM_UTF32_LE + SAMPLE.encode("utf-32-le"),
        codecs.BOM_UTF8 + SAMPLE.encode("utf-8"),
        SAMPLE.encode("utf-8"),
    ],
    ids=["utf16le-bom", "utf16be-bom", "utf16le-no-bom", "utf16be-no-bom", "utf32le-bom", "utf8-bom", "utf8"],
)
def test_decode_source_bytes_returns_the_text_for_each_encoding(raw):
    decoded = decode_source_bytes(raw)
    assert decoded == SAMPLE
    assert "\x00" not in decoded


def test_decode_source_bytes_removes_stray_nul_from_utf8_text():
    raw = b"header\x00\n" + b"value = 42\n" * 20 + b"\x00trailer\n"
    assert decode_source_bytes(raw) == "header\n" + "value = 42\n" * 20 + "trailer\n"


def test_decode_source_bytes_keeps_very_short_input_as_utf8():
    assert decode_source_bytes(b"ab\x00") == "ab"


def test_read_source_text_reads_a_powershell_style_utf16_file(tmp_path):
    target = tmp_path / "requirements.txt"
    target.write_bytes(codecs.BOM_UTF16_LE + "fastapi==0.115.0\r\nuvicorn==0.30.0\r\n".encode("utf-16-le"))
    assert read_source_text(str(target)) == "fastapi==0.115.0\r\nuvicorn==0.30.0\r\n"


def test_strip_nul_cleans_nested_structures_and_keeps_other_values():
    value = {"a": "x\x00y", "b": ["c\x00", ("d\x00", 3)], "n": None, "i": 7}
    assert strip_nul(value) == {"a": "xy", "b": ["c", ("d", 3)], "n": None, "i": 7}


def _store_with_postgres_like_checks():
    """SQLite table that rejects what PostgreSQL rejects (\\u0000 in JSON) and one marker text for isolation tests."""
    from app.services.vector_store.pgvector_store import PgVectorStore

    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        conn.execute(text(r"""
            CREATE TABLE vector_documents (
                id VARCHAR(255), collection_name VARCHAR(255), repo VARCHAR(255), doc_type VARCHAR(50),
                path TEXT, rel_path TEXT, title TEXT, folder TEXT, category TEXT, tags TEXT, heading TEXT,
                symbol TEXT, language VARCHAR(50), start_line INTEGER, end_line INTEGER, github_url TEXT,
                permalink_url TEXT, content TEXT, embedding TEXT, payload TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CHECK (instr(payload, '\u0000') = 0),
                CHECK (content IS NULL OR content <> 'REJECTED BY THE DATABASE'),
                PRIMARY KEY (collection_name, id)
            );
        """))
        conn.commit()
    return engine, PgVectorStore(engine=engine, collection_name="nul_tests", auto_init=False)


def _doc(doc_id: str, body: str, **metadata) -> VectorDocument:
    return VectorDocument(id=doc_id, text=body, dense_vector=[0.1] * 4, repo="r", path=f"{doc_id}.sql", metadata=metadata)


def test_upsert_removes_nul_from_content_payload_and_metadata():
    engine, store = _store_with_postgres_like_checks()
    assert store.upsert_documents([_doc("d1", "SELECT\x00 1", note="x\x00y")]) is True
    with engine.connect() as conn:
        content, payload = conn.execute(text("SELECT content, payload FROM vector_documents WHERE id = 'd1'")).one()
    assert content == "SELECT 1"
    assert "\x00" not in payload and "\\u0000" not in payload


def test_upsert_skips_only_the_rejected_record_and_keeps_the_rest():
    engine, store = _store_with_postgres_like_checks()
    docs = [_doc("ok-1", "first"), _doc("bad", "REJECTED BY THE DATABASE"), _doc("ok-2", "second")]
    assert store.upsert_documents(docs, batch_size=10) is True
    with engine.connect() as conn:
        stored = {row[0] for row in conn.execute(text("SELECT id FROM vector_documents")).all()}
    assert stored == {"ok-1", "ok-2"}


def test_upsert_reports_failure_when_every_record_is_rejected():
    _, store = _store_with_postgres_like_checks()
    assert store.upsert_documents([_doc("bad", "REJECTED BY THE DATABASE")]) is False


def test_rejected_record_warnings_do_not_log_the_chunk_text(caplog):
    _, store = _store_with_postgres_like_checks()
    secret_sized_text = "REJECTED BY THE DATABASE"
    long_doc = _doc("bad", secret_sized_text, note="y" * 5000)
    with caplog.at_level("WARNING", logger="contextcortex.vector_store.pgvector"):
        store.upsert_documents([long_doc, _doc("ok", "fine")])
    assert caplog.records, "expected warnings for the rejected record"
    assert all(len(r.getMessage()) < 600 for r in caplog.records)
    assert all("y" * 100 not in r.getMessage() for r in caplog.records)
