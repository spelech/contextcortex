"""Tests that read_file, grep_code, and the binary check treat UTF-16/UTF-32 text files as text, not binary."""

import codecs

import pytest

from app.services.database.engine import get_db_engine, init_db
from app.services.file_reader import FileReaderService
from app.services.text_decoding import is_binary_sample

PROC = "CREATE PROCEDURE dbo.GetLatestVersion\r\nAS\r\nSELECT TOP 1 Version FROM dbo.Releases\r\n"


@pytest.mark.parametrize(
    "sample",
    [
        codecs.BOM_UTF16_LE + PROC.encode("utf-16-le"),
        PROC.encode("utf-16-le"),
        PROC.encode("utf-16-be"),
        codecs.BOM_UTF32_LE + PROC.encode("utf-32-le"),
        PROC.encode("utf-8"),
    ],
    ids=["utf16le-bom", "utf16le-no-bom", "utf16be-no-bom", "utf32le-bom", "utf8"],
)
def test_text_samples_are_not_binary(sample):
    assert is_binary_sample(sample) is False


def test_real_binary_sample_is_binary():
    png_like = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x01\x00\x00\x00\x01\x00\x08\x06\x00\x00\x00\x5c\x72\xa8\x66" * 8
    assert is_binary_sample(png_like) is True
    assert is_binary_sample(codecs.BOM_UTF8 + b"text\x00\x01\x02\x03binary") is True


@pytest.fixture
def storage_with_utf16_proc(tmp_path, monkeypatch):
    db_file = tmp_path / "utf16_reads.db"
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", str(db_file))
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", str(db_file), raising=False)
    init_db(engine=get_db_engine(db_url, reset=True))

    storage_dir = tmp_path / "storage"
    (storage_dir / "sql").mkdir(parents=True)
    monkeypatch.setenv("LOCAL_STORAGE_PATH", str(storage_dir))
    monkeypatch.setattr("app.services.local_storage.LOCAL_STORAGE_PATH", str(storage_dir), raising=False)
    (storage_dir / "sql" / "GetLatestVersion.sql").write_bytes(codecs.BOM_UTF16_LE + PROC.encode("utf-16-le"))
    return storage_dir


def test_read_file_returns_the_text_of_a_utf16_file(storage_with_utf16_proc):
    service = FileReaderService(storage_root=str(storage_with_utf16_proc))
    result = service.read_file("sql/GetLatestVersion.sql")
    assert result["content"].splitlines() == PROC.splitlines()
    assert result["total_lines"] == 3
    assert "\x00" not in result["content"]


def test_read_file_still_refuses_real_binary_files(storage_with_utf16_proc):
    (storage_with_utf16_proc / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x01\x00" * 8)
    service = FileReaderService(storage_root=str(storage_with_utf16_proc))
    with pytest.raises(ValueError, match="binary"):
        service.read_file("logo.png")
