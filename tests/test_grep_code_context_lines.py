"""grep_code: every context line has its own, correct line number on the disk, extended-scan, and chunk paths."""

import asyncio
import json
import re

import pytest

from app.mcp.handlers.grep_handlers import _sanitize_match_lines, handle_grep_code
from app.services.code_grep_chunks import build_line_map
from app.services.code_grep_scanner import execute_code_grep
from app.services.database.engine import get_db_engine, init_db
from app.services.file_reader import FileReaderService
from app.services.indexing.processor import frontmatter_line_offset

FILE_LINES = [f"line {n}" + (" TARGET_A" if n == 47 else " TARGET_B" if n == 63 else "") for n in range(1, 100)]


def _assert_context(match, file_lines, context_lines):
    numbers = [item["line"] for item in match["context"]]
    first = max(1, match["line"] - context_lines)
    last = min(len(file_lines), match["line"] + context_lines)
    assert numbers == list(range(first, last + 1))
    for item in match["context"]:
        assert item["text"] == file_lines[item["line"] - 1]


class _NoDb:
    def __enter__(self):
        raise RuntimeError("no database in this test")

    def __exit__(self, *exc):
        return False


@pytest.fixture
def hub_reader(tmp_path, monkeypatch):
    db_file = tmp_path / "grep_ctx.db"
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setattr("app.services.database.connection.CACHE_DB_PATH", str(db_file))
    monkeypatch.setattr("app.services.database.CACHE_DB_PATH", str(db_file), raising=False)
    init_db(engine=get_db_engine(db_url, reset=True))

    hub = tmp_path / "hub"
    hub.mkdir()
    (hub / "skill.md").write_text("\n".join(FILE_LINES) + "\n", encoding="utf-8")
    reader = FileReaderService(storage_root=str(tmp_path / "storage"))
    monkeypatch.setattr(reader, "_get_authorized_indexed_paths", lambda: [{"path": str(hub), "repo": "hub-prefix"}])
    monkeypatch.setattr(reader, "_get_authorized_persistent_repos", lambda: {})
    monkeypatch.setattr("app.mcp.handlers.grep_handlers._resolve_reader_factory", lambda: (lambda: reader))
    return reader


def _grep(**kwargs):
    return json.loads(asyncio.run(handle_grep_code(**kwargs)))


@pytest.mark.parametrize("extra", [{}, {"offset": 95, "limit": 10}])
def test_indexed_path_regex_context_lines_are_consecutive(hub_reader, extra):
    # offset + limit > 100 sends the search through _scan_extended_matches.
    result = _grep(pattern=r"TARGET_\w+", is_regex=True, repo="hub-prefix", context_lines=3, **extra)
    if extra:
        assert result["matches"] == []
        result = _grep(pattern=r"TARGET_\w+", is_regex=True, repo="hub-prefix", context_lines=3, limit=100, offset=0)
    assert [m["line"] for m in result["matches"]] == [47, 63]
    for match in result["matches"]:
        _assert_context(match, FILE_LINES, 3)


def _chunk(start, end, lines, **extra):
    text = "\n".join(lines).strip()  # the indexer strips chunk text
    return {"repo": "hub-prefix", "rel_path": "docs/skill.md", "content": text, "start_line": start, "end_line": end, **extra}


def _file_chunks():
    # Chunk 2 starts with two blank lines that the strip removed; chunk 3 overlaps chunk 2.
    lines = list(FILE_LINES)
    lines[39] = lines[40] = ""
    return lines, [
        _chunk(1, 41, lines[0:41]),
        _chunk(40, 55, lines[39:55]),
        _chunk(54, 99, lines[53:99]),
        {"repo": "hub-prefix", "rel_path": "docs/skill.md", "doc_type": "summary", "is_summary": True,
         "content": "Summary\nTARGET_A is used here\nTARGET_B too", "start_line": 1, "end_line": 1},
    ]


class _Store:
    def __init__(self, chunks, with_file_chunks=True):
        self.chunks = chunks
        if with_file_chunks:
            self.get_file_chunks = lambda path, repo=None: [c for c in chunks if c["rel_path"] == path]

    def grep_chunks(self, pattern, repo=None, path_glob=None, is_regex=False, case_sensitive=False, limit=100):
        rx = re.compile(pattern if is_regex else re.escape(pattern), 0 if case_sensitive else re.IGNORECASE)
        return [c for c in self.chunks if rx.search(c["content"])][:limit]


def _chunk_grep(monkeypatch, tmp_path, store):
    monkeypatch.setattr("app.services.vector_store.get_vector_store", lambda: store)
    return execute_code_grep(
        pattern=r"TARGET_\w+", storage_root=str(tmp_path / "none"), indexed_paths=[], persistent_repos={},
        is_binary_fn=lambda p: False, db_conn_factory=_NoDb, repo="hub-prefix", is_regex=True, context_lines=3,
    )


def test_chunk_path_context_lines_have_file_line_numbers(monkeypatch, tmp_path):
    file_lines, chunks = _file_chunks()
    result = _chunk_grep(monkeypatch, tmp_path, _Store(chunks))
    # The summary chunk gives no matches, and line 47 keeps its real number after the stripped blank lines.
    assert [(m["file"], m["line"]) for m in result["matches"]] == [("docs/skill.md", 47), ("docs/skill.md", 63)]
    for match in result["matches"]:
        assert match["match_text"] == file_lines[match["line"] - 1]
        _assert_context(match, file_lines, 3)


def test_chunk_path_without_file_chunks_gives_consecutive_numbers(monkeypatch, tmp_path):
    # Only the matched chunks are known, so the stripped start of chunk 2 cannot be placed; the numbers still go up by one.
    _, chunks = _file_chunks()
    result = _chunk_grep(monkeypatch, tmp_path, _Store(chunks, with_file_chunks=False))
    assert len(result["matches"]) == 2
    for match in result["matches"]:
        numbers = [item["line"] for item in match["context"]]
        assert numbers == list(range(match["line"] - 3, match["line"] + 4))


def test_chunk_context_continues_past_the_chunk_edge():
    lines = [f"row {n}" for n in range(1, 21)]
    line_map = build_line_map([_chunk(1, 10, lines[0:10]), _chunk(11, 20, lines[10:20])])
    assert [line_map[n] for n in range(1, 21)] == lines


def test_sanitizer_renumbers_context_lines_that_share_one_number():
    match = {
        "repo": "hub-prefix", "file": "skill.md", "line": 47, "match_text": "line 47 TARGET_A",
        "context": [{"line": 47, "text": FILE_LINES[n - 1]} for n in range(44, 51)],
    }
    sanitized = _sanitize_match_lines(match)
    assert [c["line"] for c in sanitized["context"]] == list(range(44, 51))
    assert [c["text"] for c in sanitized["context"]] == FILE_LINES[43:50]


def test_sanitizer_keeps_correct_context_lines():
    match = {"line": 2, "match_text": "b", "context": [{"line": 1, "text": "a"}, {"line": 2, "text": "b"}]}
    assert _sanitize_match_lines(match)["context"] == match["context"]


@pytest.mark.parametrize("text, expected", [
    ("---\ntitle: x\ntags: a\n---\n\n# Heading\nbody\n", 5),
    ("\r\n# Heading\r\n\r\nbody\r\n", 1),
    ("# Heading\nbody\n", 0),
])
def test_frontmatter_line_offset(text, expected):
    import frontmatter

    body = frontmatter.loads(text).content
    assert frontmatter_line_offset(text, body) == expected
    assert text.splitlines()[expected].strip() == body.splitlines()[0]
