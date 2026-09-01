import os
import pytest
from app.services.local_storage import LocalStorageService, get_local_storage_service

def test_resolve_safe_path_valid(tmp_path):
    service = LocalStorageService(storage_root=str(tmp_path))
    safe = service.resolve_safe_path("docs/spec.md")
    assert safe == os.path.abspath(tmp_path / "docs" / "spec.md")
    assert service.get_storage_root() == str(tmp_path)

def test_resolve_safe_path_traversal_rejected(tmp_path):
    service = LocalStorageService(storage_root=str(tmp_path))
    with pytest.raises(ValueError, match="Path traversal or invalid path detected"):
        service.resolve_safe_path("../secret.txt")
    with pytest.raises(ValueError, match="Path traversal or invalid path detected"):
        service.resolve_safe_path("/etc/passwd")
    with pytest.raises(ValueError, match="Path traversal or invalid path detected"):
        service.resolve_safe_path("docs/../../outside.txt")
    with pytest.raises(ValueError, match="Path traversal or invalid path detected"):
        service.resolve_safe_path("null\x00byte.md")
    with pytest.raises(ValueError, match="Path traversal or invalid path detected"):
        service.resolve_safe_path("")

def test_save_and_read_file(tmp_path):
    service = LocalStorageService(storage_root=str(tmp_path))
    res = service.save_file_content("folder/test.md", "# Hello Local Storage\nSample text", repo="local_storage", category="notes")
    assert res["status"] == "success"
    assert res["rel_path"] == "folder/test.md"
    assert os.path.exists(tmp_path / "folder" / "test.md")

    read_res = service.read_file_content("folder/test.md")
    assert read_res["content"] == "# Hello Local Storage\nSample text"
    assert read_res["size_bytes"] > 0

def test_save_bytes_and_read_nonexistent(tmp_path):
    service = LocalStorageService(storage_root=str(tmp_path))
    res = service.save_file_content("binary.bin", b"\x00\x01\x02\x03")
    assert res["status"] == "success"
    assert os.path.exists(tmp_path / "binary.bin")

    with pytest.raises(FileNotFoundError):
        service.read_file_content("missing.txt")

def test_delete_file_and_directory(tmp_path):
    service = LocalStorageService(storage_root=str(tmp_path))
    service.save_file_content("to_del.txt", "delete me")
    assert os.path.exists(tmp_path / "to_del.txt")
    deleted = service.delete_file_disk("to_del.txt")
    assert deleted is True
    assert not os.path.exists(tmp_path / "to_del.txt")

    # Deleting non-existent file
    assert service.delete_file_disk("to_del.txt") is False

    # Deleting directory
    service.save_file_content("dir_to_del/nested.txt", "nested")
    assert os.path.isdir(tmp_path / "dir_to_del")
    assert service.delete_file_disk("dir_to_del") is True
    assert not os.path.exists(tmp_path / "dir_to_del")

def test_get_file_tree(tmp_path):
    service = LocalStorageService(storage_root=str(tmp_path))
    service.save_file_content("a.md", "file a")
    service.save_file_content("sub/b.py", "print('b')")
    tree = service.get_file_tree()
    assert tree["root"] == str(tmp_path)
    assert len(tree["files"]) >= 1
    assert any(d["name"] == "sub" for d in tree["directories"])

    # Subfolder tree
    subtree = service.get_file_tree(subfolder="sub")
    assert subtree["current_folder"] == "sub"
    assert any(f["name"] == "b.py" for f in subtree["files"])

def test_get_local_storage_service_singleton(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_STORAGE_PATH", str(tmp_path / "singleton_store"))
    import app.services.local_storage as ls_mod
    ls_mod._storage_service = None
    svc = get_local_storage_service()
    assert svc.get_storage_root() == str(tmp_path / "singleton_store")
    assert get_local_storage_service() is svc
