import os
import io
import pytest
import pymupdf
from unittest.mock import patch
from fastapi.testclient import TestClient
from main import app
from app.services.local_storage import LocalStorageService
import app.services.local_storage as ls_mod
import app.services.database as db_service
import app.services.vector_store as vs_service
from app.services.pdf_extractor import MAX_PDF_SIZE_BYTES


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def setup_test_db_and_storage(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_pdf_storage.db")
    monkeypatch.setenv("CACHE_DB_PATH", test_db)
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", test_db)
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", test_db)
    db_service.init_db()

    storage_root = str(tmp_path / "storage")
    storage_svc = LocalStorageService(storage_root=storage_root)
    monkeypatch.setattr(ls_mod, "_storage_service", storage_svc)
    return storage_svc


def create_sample_pdf(pages_text: list[str]) -> bytes:
    doc = pymupdf.open()
    for text in pages_text:
        page = doc.new_page()
        if text:
            page.insert_text((50, 50), text)
    return doc.tobytes()


def test_pdf_preview_endpoint(client, setup_test_db_and_storage):
    storage = setup_test_db_and_storage
    pdf_bytes = create_sample_pdf([
        "ASD-STE100 Specification Rule 1: Use approved words only.",
        "ASD-STE100 Specification Rule 2: Keep sentences under 25 words."
    ])

    response = client.post(
        "/admin/api/storage/pdf/preview",
        files={"file": ("spec.pdf", pdf_bytes, "application/pdf")},
        data={"ocr_fallback": "false"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["filename"] == "spec.pdf"
    assert data["total_pages"] == 2
    assert data["ocr_pages_count"] == 0
    assert len(data["pages"]) == 2
    assert "Rule 1" in data["pages"][0]["text"]
    assert "Rule 2" in data["pages"][1]["text"]
    assert len(data["sample_chunks"]) >= 2

    # Verify preview did NOT write anything to disk in storage root
    target = os.path.join(storage.get_storage_root(), "spec.pdf")
    assert not os.path.exists(target)


def test_pdf_preview_validation_errors(client):
    # Missing file
    res = client.post("/admin/api/storage/pdf/preview")
    assert res.status_code == 422 or res.status_code == 400

    # Non-pdf extension
    res = client.post(
        "/admin/api/storage/pdf/preview",
        files={"file": ("invalid.txt", b"plain text", "text/plain")}
    )
    assert res.status_code == 400
    assert "pdf" in res.json().get("error", "").lower()

    # Corrupt PDF bytes
    res = client.post(
        "/admin/api/storage/pdf/preview",
        files={"file": ("corrupt.pdf", b"corrupted random data", "application/pdf")}
    )
    assert res.status_code == 400
    assert "error" in res.json()


def test_pdf_preview_oversized(client):
    with patch("app.api.routers.storage.MAX_PDF_SIZE_BYTES", 100):
        res = client.post(
            "/admin/api/storage/pdf/preview",
            files={"file": ("large.pdf", b"a" * 200, "application/pdf")}
        )
        assert res.status_code == 400
        assert "exceed" in res.json().get("error", "").lower()


def test_pdf_upload_and_indexing(client, setup_test_db_and_storage):
    storage = setup_test_db_and_storage
    pdf_bytes = create_sample_pdf([
        "Chapter 1: Standard Simplified Technical English rules and constraints.",
        "Chapter 2: Dictionary of approved nouns and verbs."
    ])

    res = client.post(
        "/admin/api/storage/upload",
        files={"file": ("docs/guide.pdf", pdf_bytes, "application/pdf")},
        data={"path": "docs/guide.pdf", "repo": "local_storage", "category": "manuals"}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["rel_path"] == "docs/guide.pdf"
    assert data.get("chunks_indexed", 0) > 0

    # Verify saved on disk
    abs_path = os.path.join(storage.get_storage_root(), "docs", "guide.pdf")
    assert os.path.exists(abs_path)

    # Verify indexed in sqlite
    with db_service.get_db_connection() as conn:
        row = conn.execute("SELECT * FROM indexed_files WHERE filepath = ?", (abs_path,)).fetchone()
        assert row is not None
        assert row["doc_type"] == "pdf"


def test_pdf_read_file_content(client, setup_test_db_and_storage):
    storage = setup_test_db_and_storage
    pdf_bytes = create_sample_pdf([
        "Page one content with introductory text.",
        "Page two content with technical instructions."
    ])

    storage.save_file("manuals/user_guide.pdf", pdf_bytes, repo="local_storage", category="manuals")

    # Read using storage service directly
    read_res = storage.read_file_content("manuals/user_guide.pdf")
    assert read_res["status"] == "success"
    assert read_res["is_pdf"] is True
    assert read_res["total_pages"] == 2
    assert "# Page 1\n" in read_res["content"]
    assert "# Page 2\n" in read_res["content"]
    assert "introductory text" in read_res["content"]

    # Read using GET endpoint
    api_res = client.get("/admin/api/storage/file?path=manuals/user_guide.pdf")
    assert api_res.status_code == 200
    api_data = api_res.json()
    assert api_data["is_pdf"] is True
    assert api_data["total_pages"] == 2
    assert "# Page 1\n" in api_data["content"]


def test_real_asd_ste100_pdf_preview_or_indexing(client):
    real_pdf = "/drives/nfs/ASD-STE100_ISSUE9.pdf"
    if not os.path.exists(real_pdf):
        pytest.skip(f"Real PDF not found at {real_pdf}")

    with open(real_pdf, "rb") as f:
        # Read the first 5 pages using pymupdf and create a mini slice to avoid huge payload test overhead
        doc = pymupdf.open(real_pdf)
        slice_doc = pymupdf.open()
        slice_doc.insert_pdf(doc, from_page=0, to_page=4)
        slice_bytes = slice_doc.tobytes()
        slice_doc.close()
        doc.close()

    res = client.post(
        "/admin/api/storage/pdf/preview",
        files={"file": ("ASD-STE100_ISSUE9_sample.pdf", slice_bytes, "application/pdf")},
        data={"ocr_fallback": "false"}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["total_pages"] == 5
    assert len(data["pages"]) == 5
    assert len(data["sample_chunks"]) > 0
