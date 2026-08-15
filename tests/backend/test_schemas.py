import pytest
from app.models.schemas import CodeSymbol, CodeChunk, MarkdownChunk, SearchRequest, CloneResult

def test_code_symbol_creation():
    sym = CodeSymbol(
        name="test_func",
        full_symbol="module.test_func",
        kind="function",
        start_line=10,
        end_line=20,
        signature="def test_func():",
        language="python"
    )
    assert sym.name == "test_func"
    assert sym.repo is None

def test_search_request_defaults():
    req = SearchRequest(query="find me")
    assert req.type == "code"
    assert req.limit == 5
    assert req.exact is True
