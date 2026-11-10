"""Storage writes against real SQLite, embedded Qdrant, and a local embedding API."""

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_test_db(tmp_path, monkeypatch):
    import app.services.database as database
    import app.services.database.connection as connection
    from app.services.vector_store import VectorStoreManager

    path = str(tmp_path / "cache.db")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path}")
    monkeypatch.setenv("CACHE_DB_PATH", path)
    monkeypatch.setattr(database, "CACHE_DB_PATH", path)
    monkeypatch.setattr(connection, "CACHE_DB_PATH", path)
    VectorStoreManager.reset_instance()
    database.get_db_engine(reset=True)
    database.init_db()
    database.set_vector_store_db_config(
        provider="qdrant", mode="embedded",
        storage_path=str(tmp_path / "vectors"), collection="storage_write_test",
    )
    yield
    VectorStoreManager.reset_instance()
    database.get_db_engine(reset=True)


@pytest.fixture
def storage_app(tmp_path, monkeypatch, isolate_test_db):
    from fastapi.testclient import TestClient
    import app.services.embeddings as embeddings
    import app.services.local_storage as local_storage

    original_embeddings = {
        name: value for name, value in vars(embeddings).items()
        if name.isupper() or name in ("_dense_model", "_sparse_model", "_openai_client")
    }

    class EmbeddingHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            texts = body["input"]
            if isinstance(texts, str):
                texts = [texts]
            response = {
                "object": "list",
                "model": body["model"],
                "data": [
                    {
                        "object": "embedding", "index": index,
                        "embedding": [0.25] * (4 if "WRONG_DIMENSION" in text else 3),
                    }
                    for index, text in enumerate(texts)
                ],
                "usage": {"prompt_tokens": 1, "total_tokens": 1},
            }
            encoded = json.dumps(response).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), EmbeddingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("AUTH_ENABLED", "false")
    service = local_storage.LocalStorageService(str(tmp_path / "storage"))
    monkeypatch.setattr(local_storage, "_storage_service", service)
    embeddings.init_embeddings(
        provider="api", dense_model="storage-test",
        litellm_url=f"http://127.0.0.1:{server.server_port}/v1",
        litellm_api_key="test-only", allow_fallback=False,
    )
    from main import app

    client = TestClient(app)
    try:
        yield client, service
    finally:
        client.close()
        embeddings._openai_client.close()
        for name, value in original_embeddings.items():
            setattr(embeddings, name, value)
        server.shutdown()
        server.server_close()
        thread.join()


def assert_metadata(path, content=None):
    import app.services.database as database

    with database.get_db_connection() as conn:
        row = conn.execute(
            "SELECT hash FROM indexed_files WHERE filepath = ?", (str(path),)
        ).fetchone()
        if content is not None:
            assert row is not None
            assert row["hash"] == hashlib.sha256(content.encode()).hexdigest()
            assert conn.execute(
                "SELECT COUNT(*) FROM file_summaries WHERE filepath = ?", (str(path),)
            ).fetchone()[0] == 1
            return
        assert row is None
        for table, column in (
            ("file_summaries", "filepath"), ("ast_symbols", "filepath"),
            ("ast_relationships", "source_filepath"), ("api_routes", "filepath"),
            ("api_client_calls", "filepath"),
        ):
            assert conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {column} = ?", (str(path),)
            ).fetchone()[0] == 0


def vector_count(store, path):
    from qdrant_client.http import models

    return store.client.count(
        collection_name=store.collection_name,
        count_filter=models.Filter(must=[
            models.FieldCondition(key="path", match=models.MatchValue(value=str(path))),
        ]),
        exact=True,
    ).count


@pytest.mark.parametrize("existing", [False, True])
def test_upsert_false_returns_500_rolls_back_disk_and_allows_retry(storage_app, existing, caplog):
    from app.services.vector_store import get_vector_store

    client, service = storage_app
    original = "def original():\n    return 'original indexed content'\n"
    path = service.resolve_safe_path("example.py")
    if existing:
        response = client.post("/admin/api/storage/upload", json={
            "path": "example.py", "content": original,
        })
        assert response.status_code == 200
        assert response.json()["chunks_indexed"] > 0
    store = get_vector_store()
    assert store.client.get_collection(store.collection_name).config.params.vectors["dense"].size == 3
    if existing:
        assert vector_count(store, path) > 0
        assert_metadata(path, original)

    request = client.put if existing else client.post
    endpoint = "/admin/api/storage/file" if existing else "/admin/api/storage/upload"
    response = request(endpoint, json={
        "path": "example.py",
        "content": "def replacement():\n    return 'WRONG_DIMENSION'\n",
    })
    # This disturbance must reach real Qdrant upsert, not fail during embedding.
    assert "Error upserting documents into Qdrant collection" in caplog.text
    assert response.status_code == 500
    assert response.json() == {
        "error": "Failed to replace storage file." if existing else "Failed to upload storage file.",
    }
    assert_metadata(path)
    assert vector_count(store, path) == 0
    if existing:
        assert client.get("/admin/api/storage/file", params={"path": "example.py"}).json()["content"] == original
        # Reindex the restored file directly: it must not be skipped as already indexed.
        result = service.index_file("example.py")
        assert result["chunks_indexed"] > 0
    else:
        assert client.get("/admin/api/storage/file", params={"path": "example.py"}).status_code == 404
        response = request(endpoint, json={"path": "example.py", "content": original})
        assert response.status_code == 200
        assert response.json()["chunks_indexed"] > 0
    assert_metadata(path, original)
    assert vector_count(store, path) > 0
    assert not list(Path(service.storage_root).rglob("bak_*"))


def test_delete_false_is_not_reported_as_success(storage_app, caplog):
    from app.services.vector_store import get_vector_store, VectorStoreManager

    client, service = storage_app
    original = "# Original\nAlready indexed document."
    assert client.post("/admin/api/storage/upload", json={
        "path": "note.md", "content": original,
    }).status_code == 200
    store = get_vector_store()
    store.client.close()
    response = client.put("/admin/api/storage/file", json={
        "path": "note.md", "content": "# New\nReplacement document.",
    })
    assert "Error deleting by path" in caplog.text
    assert response.status_code == 500
    assert response.json() == {"error": "Failed to replace storage file."}
    path = service.resolve_safe_path("note.md")
    assert_metadata(path)
    assert service.read_file_content("note.md")["content"] == original
    VectorStoreManager.reset_instance()
    result = service.index_file("note.md")
    assert result["chunks_indexed"] > 0
    assert_metadata(path, original)
    assert vector_count(get_vector_store(), path) == result["chunks_indexed"]


@pytest.mark.parametrize("existing", [False, True])
def test_store_initialization_exception_rolls_back_upload(storage_app, tmp_path, existing):
    import app.services.database as database
    from app.services.vector_store import VectorStoreManager

    client, service = storage_app
    original = "# Original\nDocument before initialization failure."
    if existing:
        assert client.post("/admin/api/storage/upload", json={
            "path": "note.md", "content": original,
        }).status_code == 200
    vector_path = database.get_vector_store_db_config()["storage_path"]
    blocked_path = tmp_path / "not_a_directory"
    blocked_path.write_text("Blocks embedded Qdrant initialization.")
    VectorStoreManager.reset_instance()
    database.set_vector_store_db_config(storage_path=str(blocked_path))
    response = client.post("/admin/api/storage/upload", json={
        "path": "note.md", "content": "# New\nDocument to index.",
    })
    assert response.status_code == 500
    assert response.json() == {"error": "Failed to upload storage file."}
    path = service.resolve_safe_path("note.md")
    if existing:
        assert_metadata(path, original)
        assert service.read_file_content("note.md")["content"] == original
    else:
        assert_metadata(path)
        assert client.get("/admin/api/storage/file", params={"path": "note.md"}).status_code == 404
    database.set_vector_store_db_config(storage_path=vector_path)
    response = client.post("/admin/api/storage/upload", json={
        "path": "note.md", "content": "# New\nDocument to index.",
    })
    assert response.status_code == 200
    assert response.json()["chunks_indexed"] > 0


def test_failed_multichunk_upsert_removes_partial_vectors(storage_app, caplog):
    from app.services.vector_store import get_vector_store

    client, service = storage_app
    store = get_vector_store()
    response = client.post("/admin/api/storage/upload", json={
        "path": "partial.md",
        "content": "# First\nValid first chunk.\n\n# Second\nWRONG_DIMENSION second chunk.",
    })
    assert "Error upserting documents into Qdrant collection" in caplog.text
    assert response.status_code == 500
    assert_metadata(service.resolve_safe_path("partial.md"))
    assert store.client.count(collection_name=store.collection_name, exact=True).count == 0
    assert not Path(service.resolve_safe_path("partial.md")).exists()


def test_empty_replacement_succeeds_without_leaving_old_vectors(storage_app):
    from app.services.vector_store import get_vector_store

    client, service = storage_app
    assert client.post("/admin/api/storage/upload", json={
        "path": "note.md", "content": "# Original\nContent with vectors.",
    }).status_code == 200
    path = service.resolve_safe_path("note.md")
    store = get_vector_store()
    assert vector_count(store, path) > 0
    response = client.put("/admin/api/storage/file", json={"path": "note.md", "content": ""})
    assert response.status_code == 200
    assert response.json()["chunks_indexed"] == 0
    assert service.read_file_content("note.md")["content"] == ""
    assert_metadata(path, "")
    assert vector_count(store, path) == 0
