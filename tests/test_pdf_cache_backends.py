import hashlib
import json
import os
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pymupdf
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

import app.services.database as db_service
import app.services.embeddings as embeddings
import app.services.local_storage as storage_module
from app.services.database.engine import dispose_global_engine
from app.services.local_storage import LocalStorageService
from app.services.vector_store import VectorStoreManager
from main import app


@pytest.fixture
def gateway():
    state = {"ocr_text": "", "ocr_available": True}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path == "/v1/embeddings":
                inputs = request["input"]
                if isinstance(inputs, str):
                    inputs = [inputs]
                response = {
                    "object": "list",
                    "model": request["model"],
                    "data": [
                        {"object": "embedding", "index": i, "embedding": [0.1, 0.2, 0.3]}
                        for i in range(len(inputs))
                    ],
                    "usage": {"prompt_tokens": 1, "total_tokens": 1},
                }
            elif self.path == "/v1/chat/completions":
                if not state["ocr_available"]:
                    self.send_error(503)
                    return
                response = {
                    "id": "test-ocr",
                    "object": "chat.completion",
                    "created": 1,
                    "model": request["model"],
                    "choices": [{
                        "index": 0,
                        "message": {"role": "assistant", "content": state["ocr_text"]},
                        "finish_reason": "stop",
                    }],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                }
            else:
                self.send_error(404)
                return
            body = json.dumps(response).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state["url"] = f"http://127.0.0.1:{server.server_port}/v1"
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.fixture(params=("sqlite", "postgresql"))
def storage(request, tmp_path, monkeypatch, gateway):
    admin_engine = None
    schema = None
    if request.param == "postgresql":
        database_url = os.getenv("TEST_POSTGRES_URL")
        if not database_url:
            pytest.skip("TEST_POSTGRES_URL is required for native PostgreSQL tests")
        admin_engine = create_engine(database_url)
        schema = f"pdf_cache_{uuid.uuid4().hex}"
        with admin_engine.begin() as conn:
            conn.execute(text(f"CREATE SCHEMA {schema}"))
        database_url = make_url(database_url).update_query_dict(
            {"options": f"-csearch_path={schema},public"}
        ).render_as_string(hide_password=False)
    else:
        database_path = str(tmp_path / "pdf_cache.db")
        database_url = f"sqlite:///{database_path}"
        monkeypatch.setattr(db_service, "CACHE_DB_PATH", database_path)
        monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", database_path)

    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("AUTH_ENABLED", "false")
    dispose_global_engine()
    try:
        db_service.init_db(vault_path=str(tmp_path))
        db_service.set_embedding_db_config(
            provider="api",
            dense_model="test-embedding",
            litellm_url=gateway["url"],
            litellm_api_key="test-only",
            vision_ocr_model="test-vision",
        )
        db_service.set_vector_store_db_config(
            provider="qdrant",
            mode="embedded",
            storage_path=str(tmp_path / "vectors"),
        )
        embeddings.init_embeddings(provider="api")
        service = LocalStorageService(str(tmp_path / "storage"))
        monkeypatch.setattr(storage_module, "_storage_service", service)
        yield service
    finally:
        VectorStoreManager.reset_instance()
        dispose_global_engine()
        if admin_engine is not None:
            with admin_engine.begin() as conn:
                conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
            admin_engine.dispose()


def make_pdf(content, scanned):
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((50, 50), content)
        if not scanned:
            return document.tobytes()
        image = page.get_pixmap().tobytes("png")
        with pymupdf.open() as scan:
            scan.new_page().insert_image(page.rect, stream=image)
            return scan.tobytes()


def cache_row(filepath):
    with db_service.get_db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM pdf_extracted_cache WHERE filepath = ?", (filepath,)
        ).fetchone()
        return dict(row) if row is not None else None


@pytest.mark.parametrize("scanned", (False, True), ids=("text", "ocr"))
def test_pdf_upload_replacement_persists_cache_and_index(storage, gateway, scanned):
    client = TestClient(app)
    path = "manuals/orchid.pdf"
    abs_path = storage.resolve_safe_path(path)
    for version, repo in (("original", "first"), ("replacement", "second")):
        content = f"ORCHID 4729: {version} amber invoice routing instructions for testing."
        gateway["ocr_text"] = content
        response = client.post(
            "/admin/api/storage/upload",
            files={"file": ("orchid.pdf", make_pdf(content, scanned), "application/pdf")},
            data={"path": path, "repo": repo},
        )
        assert response.status_code == 200
        assert response.json()["chunks_indexed"] > 0
        row = cache_row(abs_path)
        assert row is not None
        assert row["repo"] == repo
        assert version in row["extracted_text"]
        assert row["ocr_pages_count"] == int(scanned)
        assert row["hash"] == hashlib.sha256(row["extracted_text"].encode()).hexdigest()
        with db_service.get_db_connection() as conn:
            indexed = conn.execute(
                "SELECT hash FROM indexed_files WHERE filepath = ?", (abs_path,)
            ).fetchone()
            assert indexed["hash"] == row["hash"]
        gateway["ocr_available"] = False
        read = client.get("/admin/api/storage/file", params={"path": path})
        assert read.status_code == 200
        assert read.json()["content"] == row["extracted_text"]
        gateway["ocr_available"] = True

    assert client.delete("/admin/api/storage/file", params={"path": path}).status_code == 200
    assert cache_row(abs_path) is None
    assert not os.path.exists(abs_path)


@pytest.mark.parametrize("scanned", (False, True), ids=("text", "ocr"))
def test_pdf_read_populates_and_refreshes_existing_cache(storage, gateway, scanned):
    client = TestClient(app)
    path = "manuals/read-through.pdf"
    abs_path = storage.resolve_safe_path(path)
    for version in ("original", "replacement"):
        content = f"ORCHID 4729: {version} amber invoice routing instructions for testing."
        gateway["ocr_text"] = content
        storage.save_file_content(path, make_pdf(content, scanned))
        if version == "replacement":
            stale_mtime = cache_row(abs_path)["mtime"] + 2
            os.utime(abs_path, (stale_mtime, stale_mtime))
        response = client.get("/admin/api/storage/file", params={"path": path})
        assert response.status_code == 200
        row = cache_row(abs_path)
        assert row is not None
        assert version in row["extracted_text"]
        assert response.json()["content"] == row["extracted_text"]
        assert row["ocr_pages_count"] == int(scanned)
        assert row["mtime"] == os.path.getmtime(abs_path)
        assert version in json.loads(row["pages_json"])[0]["text"]
