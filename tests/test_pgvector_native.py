"""Native pgvector regressions; requires an explicit, disposable TEST_POSTGRES_URL."""

import json
import os
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from openai import OpenAI
from sqlalchemy import create_engine, text

from app.services import embeddings
from app.services.database.engine import get_db_url
from app.services.vector_store.pgvector_store import PgVectorStore


@pytest.fixture
def native_engine():
    url = os.getenv("TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Set TEST_POSTGRES_URL to a disposable PostgreSQL database with pgvector")
    schema = f"pg54_{uuid.uuid4().hex}"
    admin = create_engine(get_db_url(url), hide_parameters=True)
    engine = None
    try:
        with admin.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.execute(text(f"CREATE SCHEMA {schema}"))
        engine = create_engine(
            get_db_url(url),
            connect_args={"options": f"-csearch_path={schema},public"},
            hide_parameters=True,
        )
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        admin.dispose()


@pytest.fixture
def native_embeddings(monkeypatch):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            inputs = request["input"]
            if isinstance(inputs, str):
                inputs = [inputs]
            body = json.dumps({
                "object": "list",
                "model": "native-test",
                "data": [
                    {"object": "embedding", "index": i,
                     "embedding": [1.0, 0.0] if value == "wrong-size" else [1.0, 0.0, 0.0]}
                    for i, value in enumerate(inputs)
                ],
                "usage": {"prompt_tokens": 1, "total_tokens": 1},
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = OpenAI(base_url=f"http://127.0.0.1:{server.server_port}/v1", api_key="native-test")
    monkeypatch.setattr(embeddings, "EMBEDDING_PROVIDER", "api")
    monkeypatch.setattr(embeddings, "DENSE_MODEL_NAME", "native-test")
    monkeypatch.setattr(embeddings, "_openai_client", client)
    try:
        yield
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        thread.join()


def create_legacy_table(engine, dimension=3, with_collection=False):
    collection = "collection_name VARCHAR(255)," if with_collection else ""
    with engine.begin() as conn:
        conn.execute(text(f"""
            CREATE TABLE vector_documents (
                id VARCHAR(255) PRIMARY KEY, {collection}
                repo VARCHAR(255), doc_type VARCHAR(50) DEFAULT 'doc',
                path TEXT, rel_path TEXT, title TEXT, folder TEXT, category TEXT,
                tags JSONB, heading TEXT, symbol TEXT, language VARCHAR(50),
                start_line INTEGER, end_line INTEGER, github_url TEXT,
                permalink_url TEXT, content TEXT, embedding vector({dimension}),
                payload JSONB, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("""
            INSERT INTO vector_documents (id, content, payload)
            VALUES ('legacy', 'preserved', '{"content": "preserved"}')
        """))


def primary_key_columns(conn):
    return conn.execute(text("""
        SELECT a.attname FROM pg_index i
        JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
        WHERE i.indrelid = to_regclass('vector_documents') AND i.indisprimary
        ORDER BY a.attname
    """)).scalars().all()


@pytest.mark.parametrize("legacy", [False, True])
def test_native_initialization_and_collection_isolation(native_engine, native_embeddings, legacy):
    if legacy:
        create_legacy_table(native_engine)
    a = PgVectorStore(engine=native_engine, collection_name="a", dimension=3)
    b = PgVectorStore(engine=native_engine, collection_name="b", dimension=3)
    assert a.ensure_collection() is True
    assert a.health_check()[0] is True
    with native_engine.connect() as conn:
        assert primary_key_columns(conn) == ["collection_name", "id"]
        assert conn.execute(text("""
            SELECT count(*) FROM pg_indexes
            WHERE schemaname = current_schema() AND indexdef LIKE '%USING hnsw%'
        """)).scalar_one() == 1
        if legacy:
            assert conn.execute(text("""
                SELECT collection_name, content FROM vector_documents WHERE id = 'legacy'
            """)).one() == ("knowledge_rag_v1", "preserved")

    for store, content, vector in [(a, "A", [1.0, 0.0, 0.0]), (b, "B", [0.0, 1.0, 0.0])]:
        assert store.upsert_documents([{
            "id": "shared", "text": content, "dense_vector": vector,
            "path": "same.py", "repo": "same",
        }])
    assert a.upsert_documents([{
        "id": "shared", "text": "A updated", "dense_vector": [1.0, 0.0, 0.0],
        "path": "same.py", "repo": "same",
    }])
    assert a.get_stats()["points_count"] == b.get_stats()["points_count"] == 1
    result_a, result_b = a.search("horizontal"), b.search("horizontal")
    assert [(r.id, r.payload["content"], r.score) for r in result_a] == [
        ("shared", "A updated", 1.0)
    ]
    assert [(r.id, r.payload["content"], r.score) for r in result_b] == [("shared", "B", 0.0)]
    with pytest.raises(ValueError, match="Vector dimension mismatch"):
        a.search("wrong-size")

    assert a.delete_by_path("same.py")
    assert a.get_stats()["points_count"] == 0
    assert b.get_stats()["points_count"] == 1
    assert a.delete_by_repo("same")
    assert a.delete_collection()
    assert b.get_stats()["points_count"] == 1
    assert b.delete_by_repo("same")
    assert b.get_stats()["points_count"] == 0
    assert b.upsert_documents([{"id": "again", "text": "B", "dense_vector": [0.0, 1.0, 0.0]}])
    assert b.delete_collection()
    assert b.search("horizontal") == []


def test_native_migrates_null_legacy_collection(native_engine):
    create_legacy_table(native_engine, with_collection=True)
    PgVectorStore(engine=native_engine, dimension=3)
    with native_engine.connect() as conn:
        assert conn.execute(text("SELECT collection_name FROM vector_documents")).scalar_one() == "knowledge_rag_v1"
        assert primary_key_columns(conn) == ["collection_name", "id"]


@pytest.mark.parametrize("legacy", [False, True])
def test_native_initialization_error_is_explicit_and_atomic(native_engine, legacy):
    if legacy:
        create_legacy_table(native_engine, dimension=2001)
    with pytest.raises(RuntimeError, match="initializ") as error:
        PgVectorStore(engine=native_engine, dimension=2001)
    assert error.value.__cause__ is not None
    with native_engine.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar_one() == 1
        if legacy:
            assert primary_key_columns(conn) == ["id"]
            assert conn.execute(text("""
                SELECT count(*) FROM pg_attribute
                WHERE attrelid = to_regclass('vector_documents') AND attname = 'collection_name'
            """)).scalar_one() == 0
            assert conn.execute(text("SELECT content FROM vector_documents")).scalar_one() == "preserved"
        else:
            assert conn.execute(text("SELECT to_regclass('vector_documents')")).scalar_one() is None


@pytest.mark.parametrize("collection", ["a", "other"])
def test_native_dimension_mismatch_preserves_populated_table(native_engine, collection):
    owner = PgVectorStore(engine=native_engine, collection_name=collection, dimension=3)
    assert owner.upsert_documents([{
        "id": "preserve", "text": "keep me", "dense_vector": [1.0, 0.0, 0.0],
    }])
    with pytest.raises(ValueError, match="dimension.*rebuild"):
        PgVectorStore(engine=native_engine, collection_name="a", dimension=2)
    assert owner.get_stats()["points_count"] == 1
    with native_engine.connect() as conn:
        assert conn.execute(text("SELECT content, embedding::text FROM vector_documents")).one() == (
            "keep me", "[1,0,0]"
        )


def test_native_dimension_change_after_explicit_clear(native_engine):
    store = PgVectorStore(engine=native_engine, dimension=3)
    assert store.upsert_documents([{"id": "old", "dense_vector": [1.0, 0.0, 0.0]}])
    assert store.clear_collection()
    rebuilt = PgVectorStore(engine=native_engine, dimension=2)
    assert rebuilt.upsert_documents([{"id": "new", "dense_vector": [1.0, 0.0]}])
    assert rebuilt.get_stats()["points_count"] == 1
