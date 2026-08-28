import pytest
from fastapi.testclient import TestClient
from main import app
from app.services.auth import get_auth_service, Role
from app.services.local_storage import LocalStorageService
import app.services.local_storage as ls_mod

@pytest.fixture
def client():
    return TestClient(app)

def test_storage_upload_and_get_file(client, tmp_path, monkeypatch):
    monkeypatch.setattr(ls_mod, "_storage_service", LocalStorageService(storage_root=str(tmp_path)))

    # Upload file JSON
    res = client.post("/admin/api/storage/upload", json={
        "path": "test_folder/note.md",
        "content": "# Test Note\nHello world",
        "repo": "local_storage",
        "category": "docs"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["rel_path"] == "test_folder/note.md"

    # Get file
    get_res = client.get("/admin/api/storage/file?path=test_folder/note.md")
    assert get_res.status_code == 200
    assert get_res.json()["content"] == "# Test Note\nHello world"

    # Get tree
    tree_res = client.get("/admin/api/storage/tree")
    assert tree_res.status_code == 200
    assert len(tree_res.json()["directories"]) >= 1

    # Delete file
    del_res = client.delete("/admin/api/storage/file?path=test_folder/note.md")
    assert del_res.status_code == 200

def test_storage_upload_multipart_and_put(client, tmp_path, monkeypatch):
    monkeypatch.setattr(ls_mod, "_storage_service", LocalStorageService(storage_root=str(tmp_path)))

    # Upload via multipart form
    res = client.post(
        "/admin/api/storage/upload",
        files={"file": ("upload.txt", b"Multipart content", "text/plain")},
        data={"path": "uploads/upload.txt", "repo": "local_storage", "category": "uploads"}
    )
    assert res.status_code == 200
    assert res.json()["status"] == "success"
    assert res.json()["rel_path"] == "uploads/upload.txt"

    # Read uploaded file
    get_res = client.get("/admin/api/storage/file?path=uploads/upload.txt")
    assert get_res.status_code == 200
    assert get_res.json()["content"] == "Multipart content"

    # Replace file via PUT
    put_res = client.put("/admin/api/storage/file", json={
        "path": "uploads/upload.txt",
        "content": "Replaced content",
        "repo": "local_storage",
        "category": "uploads"
    })
    assert put_res.status_code == 200
    assert put_res.json()["status"] == "success"

    # Verify replacement
    get_res2 = client.get("/admin/api/storage/file?path=uploads/upload.txt")
    assert get_res2.status_code == 200
    assert get_res2.json()["content"] == "Replaced content"

def test_storage_validation_and_errors(client, tmp_path, monkeypatch):
    monkeypatch.setattr(ls_mod, "_storage_service", LocalStorageService(storage_root=str(tmp_path)))

    # Path traversal upload
    res = client.post("/admin/api/storage/upload", json={
        "path": "../secret.txt",
        "content": "illegal"
    })
    assert res.status_code == 400

    # Path traversal get
    res = client.get("/admin/api/storage/file?path=../secret.txt")
    assert res.status_code == 400

    # Non-existent file get
    res = client.get("/admin/api/storage/file?path=nonexistent.txt")
    assert res.status_code == 404

    # Empty payload upload
    res = client.post("/admin/api/storage/upload", json={})
    assert res.status_code == 400

def test_ingestion_catalog_endpoint(client):
    res = client.get("/admin/api/ingestion/catalog?source_type=all&detail_level=summary")
    assert res.status_code == 200
    data = res.json()
    assert "git_repositories" in data
    assert "monitored_paths" in data
    assert "local_storage" in data
    assert data["source_type"] == "all"
    assert data["detail_level"] == "summary"

    # Test detailed filter
    res_det = client.get("/admin/api/ingestion/catalog?source_type=local_storage&detail_level=detailed")
    assert res_det.status_code == 200
    det_data = res_det.json()
    assert det_data["local_storage"] is not None
    assert "files" in det_data
