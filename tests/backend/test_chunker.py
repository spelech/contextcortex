import pytest
from app.services.chunker import detect_language, split_by_length, chunk_markdown

def test_detect_language():
    assert detect_language("test.py") == "python"
    assert detect_language("test.js") == "javascript"
    assert detect_language("test.unknown") == "text"

def test_split_by_length():
    text = "line1\nline2\nline3\n"
    chunks = split_by_length(text, heading="Root", max_chars=10, overlap=0)
    assert len(chunks) > 0
    assert chunks[0]["heading"] == "Root"

def test_chunk_markdown():
    text = "# Header 1\ncontent 1\n## Header 2\ncontent 2"
    chunks = chunk_markdown(text, max_chars=100, overlap=0)
    assert len(chunks) == 2
    assert chunks[0].heading == "Header 1"
    assert chunks[1].heading == "Header 2"
