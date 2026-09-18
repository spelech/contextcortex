import os
import pytest
from app.services.database.engine import get_db_engine, init_db
from app.services.database.connection import (
    get_db_connection,
    set_file_settings,
    get_file_settings,
)
from app.services.file_reader import (
    FileReaderService,
    get_file_reader_service,
)


def setup_test_env(tmp_path, monkeypatch):
    """Sets up an isolated SQLite DB and storage directory for testing."""
    db_file = tmp_path / "test_file_reader.db"
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", str(db_file))
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", str(db_file), raising=False)
    engine = get_db_engine(db_url, reset=True)
    init_db(engine=engine)

    storage_dir = tmp_path / "storage"
    storage_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LOCAL_STORAGE_PATH", str(storage_dir))
    monkeypatch.setattr("app.services.local_storage.LOCAL_STORAGE_PATH", str(storage_dir), raising=False)

    return storage_dir


def test_safe_path_resolution_local_storage(tmp_path, monkeypatch):
    storage_dir = setup_test_env(tmp_path, monkeypatch)
    service = FileReaderService(storage_root=str(storage_dir))

    # Create file in storage
    sub_file = storage_dir / "docs" / "guide.md"
    sub_file.parent.mkdir(parents=True, exist_ok=True)
    sub_file.write_text("# Guide", encoding="utf-8")

    # Relative path without repo
    abs_path, source = service.resolve_safe_path("docs/guide.md")
    assert abs_path == str(sub_file.resolve())
    assert source == "local_storage"

    # Relative path with repo="local_storage"
    abs_path2, source2 = service.resolve_safe_path("docs/guide.md", repo="local_storage")
    assert abs_path2 == str(sub_file.resolve())
    assert source2 == "local_storage"

    # Absolute path inside storage root
    abs_path3, source3 = service.resolve_safe_path(str(sub_file.resolve()))
    assert abs_path3 == str(sub_file.resolve())
    assert source3 == "local_storage"


def test_safe_path_resolution_indexed_paths(tmp_path, monkeypatch):
    storage_dir = setup_test_env(tmp_path, monkeypatch)
    watched_dir = tmp_path / "watched_repo"
    watched_dir.mkdir(parents=True, exist_ok=True)

    # Register watched_dir in DB indexed_paths
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO indexed_paths (path, type, enabled, repo, category) VALUES (?, ?, 1, ?, ?)",
            (str(watched_dir.resolve()), "directory", "my_repo", "code")
        )
        conn.commit()

    test_file = watched_dir / "src" / "main.py"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text("print('hello')", encoding="utf-8")

    service = FileReaderService(storage_root=str(storage_dir))

    # Relative path with repo
    abs_path, source = service.resolve_safe_path("src/main.py", repo="my_repo")
    assert abs_path == str(test_file.resolve())
    assert source == "indexed_path"

    # Relative path without repo (resolves against matching indexed path where file exists)
    abs_path2, source2 = service.resolve_safe_path("src/main.py")
    assert abs_path2 == str(test_file.resolve())
    assert source2 == "indexed_path"

    # Absolute path matching watched directory
    abs_path3, source3 = service.resolve_safe_path(str(test_file.resolve()))
    assert abs_path3 == str(test_file.resolve())
    assert source3 == "indexed_path"


def test_path_traversal_and_invalid_paths_rejected(tmp_path, monkeypatch):
    storage_dir = setup_test_env(tmp_path, monkeypatch)
    watched_dir = tmp_path / "watched_repo"
    watched_dir.mkdir(parents=True, exist_ok=True)
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO indexed_paths (path, type, enabled, repo) VALUES (?, ?, 1, ?)",
            (str(watched_dir.resolve()), "directory", "my_repo")
        )
        conn.commit()

    service = FileReaderService(storage_root=str(storage_dir))

    # Path traversal with ..
    with pytest.raises(ValueError, match="traversal|invalid"):
        service.resolve_safe_path("../secret.txt")

    with pytest.raises(ValueError, match="traversal|invalid"):
        service.resolve_safe_path("docs/../../etc/passwd")

    with pytest.raises(ValueError, match="traversal|invalid"):
        service.resolve_safe_path("..\\windows\\traversal")

    # Null bytes
    with pytest.raises(ValueError, match="traversal|invalid"):
        service.resolve_safe_path("file\x00name.txt")

    # Empty path
    with pytest.raises(ValueError, match="traversal|invalid"):
        service.resolve_safe_path("")

    # Absolute path outside any authorized roots
    with pytest.raises(ValueError, match="outside authorized|traversal|invalid"):
        service.resolve_safe_path("/etc/shadow")

    # Outside root with repo specified
    with pytest.raises(ValueError, match="outside authorized|traversal|invalid"):
        service.resolve_safe_path("/etc/shadow", repo="my_repo")

    # Symlink pointing outside authorized root
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("secret", encoding="utf-8")
    symlink_file = storage_dir / "escape_link.txt"
    try:
        symlink_file.symlink_to(outside_file)
        with pytest.raises(ValueError, match="outside authorized|traversal|invalid"):
            service.resolve_safe_path("escape_link.txt")
    except (OSError, NotImplementedError):
        # Symlinks may not be permitted on some filesystems
        pass


def test_read_text_file_full_and_line_slicing(tmp_path, monkeypatch):
    storage_dir = setup_test_env(tmp_path, monkeypatch)
    service = FileReaderService(storage_root=str(storage_dir))

    # Create a 10-line text file
    lines = [f"Line {i}" for i in range(1, 11)]
    file_content = "\n".join(lines)
    test_file = storage_dir / "sample.txt"
    test_file.write_text(file_content, encoding="utf-8")

    # Full read
    res = service.read_file("sample.txt")
    assert res["filepath"] == "sample.txt"
    assert res["content"] == file_content
    assert res["start_line"] == 1
    assert res["end_line"] == 10
    assert res["total_lines"] == 10
    assert res["size_bytes"] == len(file_content.encode("utf-8"))
    assert res["truncated"] is False
    assert res["source"] == "local_storage"

    # Line slicing (start_line=3, end_line=6, inclusive)
    res_slice = service.read_file("sample.txt", start_line=3, end_line=6)
    expected_slice = "\n".join([f"Line {i}" for i in range(3, 7)])
    assert res_slice["content"] == expected_slice
    assert res_slice["start_line"] == 3
    assert res_slice["end_line"] == 6
    assert res_slice["total_lines"] == 10
    assert res_slice["truncated"] is False

    # Single line slice (start_line=1, end_line=1)
    res_single = service.read_file("sample.txt", start_line=1, end_line=1)
    assert res_single["content"] == "Line 1"
    assert res_single["start_line"] == 1
    assert res_single["end_line"] == 1
    assert res_single["truncated"] is False

    # Slice past EOF
    res_eof = service.read_file("sample.txt", start_line=15, end_line=20)
    assert res_eof["content"] == ""
    assert res_eof["total_lines"] == 10
    assert res_eof["truncated"] is False

    # Invalid line range (start_line > end_line)
    with pytest.raises(ValueError, match="start_line cannot be greater than end_line"):
        service.read_file("sample.txt", start_line=5, end_line=2)


def test_read_file_capping_max_lines_and_truncation(tmp_path, monkeypatch):
    storage_dir = setup_test_env(tmp_path, monkeypatch)
    service = FileReaderService(storage_root=str(storage_dir))

    # Create a 50-line text file
    lines = [f"Line {i}" for i in range(1, 51)]
    test_file = storage_dir / "large.txt"
    test_file.write_text("\n".join(lines), encoding="utf-8")

    # Explicit max_lines=5
    res = service.read_file("large.txt", max_lines=5)
    assert res["content"] == "\n".join([f"Line {i}" for i in range(1, 6)])
    assert res["start_line"] == 1
    assert res["end_line"] == 5
    assert res["total_lines"] == 50
    assert res["truncated"] is True

    # Setting cap via get_file_settings() (note: set_file_settings has min 10 floor)
    set_file_settings({"read_file_max_lines": 15})
    res_settings = service.read_file("large.txt", max_lines=None)
    assert res_settings["content"] == "\n".join([f"Line {i}" for i in range(1, 16)])
    assert res_settings["start_line"] == 1
    assert res_settings["end_line"] == 15
    assert res_settings["total_lines"] == 50
    assert res_settings["truncated"] is True

    # Sliced read that exceeds max_lines cap
    res_sliced_cap = service.read_file("large.txt", start_line=10, end_line=30, max_lines=5)
    assert res_sliced_cap["content"] == "\n".join([f"Line {i}" for i in range(10, 15)])
    assert res_sliced_cap["start_line"] == 10
    assert res_sliced_cap["end_line"] == 14
    assert res_sliced_cap["total_lines"] == 50
    assert res_sliced_cap["truncated"] is True


def test_binary_file_detection_and_rejection(tmp_path, monkeypatch):
    storage_dir = setup_test_env(tmp_path, monkeypatch)
    service = FileReaderService(storage_root=str(storage_dir))

    bin_file = storage_dir / "image.png"
    bin_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")

    txt_file = storage_dir / "text.txt"
    txt_file.write_text("Plain text content", encoding="utf-8")

    assert service.is_binary_file(str(bin_file.resolve())) is True
    assert service.is_binary_file(str(txt_file.resolve())) is False

    with pytest.raises(ValueError, match="[Bb]inary"):
        service.read_file("image.png")


def test_read_nonexistent_file_raises_not_found(tmp_path, monkeypatch):
    storage_dir = setup_test_env(tmp_path, monkeypatch)
    service = FileReaderService(storage_root=str(storage_dir))

    with pytest.raises(FileNotFoundError):
        service.read_file("does_not_exist.txt")


def test_get_file_reader_service_singleton(tmp_path, monkeypatch):
    storage_dir = setup_test_env(tmp_path, monkeypatch)
    service1 = get_file_reader_service()
    service2 = get_file_reader_service()
    assert service1 is service2
    assert isinstance(service1, FileReaderService)
