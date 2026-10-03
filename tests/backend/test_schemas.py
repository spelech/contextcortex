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
    assert req.dense_weight is None
    assert req.search_mode == "hybrid"

def test_search_request_dense_weight_boundaries():
    from pydantic import ValidationError

    # Valid boundary values: 0.0, 0.5, 1.0
    r0 = SearchRequest(query="test", dense_weight=0.0)
    assert r0.dense_weight == 0.0
    r_mid = SearchRequest(query="test", dense_weight=0.5)
    assert r_mid.dense_weight == 0.5
    r1 = SearchRequest(query="test", dense_weight=1.0)
    assert r1.dense_weight == 1.0

    # Negative out-of-bounds (< 0.0)
    with pytest.raises(ValidationError):
        SearchRequest(query="test", dense_weight=-0.001)

    # Upper out-of-bounds (> 1.0)
    with pytest.raises(ValidationError):
        SearchRequest(query="test", dense_weight=1.001)

    # Non-numeric
    with pytest.raises(ValidationError):
        SearchRequest(query="test", dense_weight="not-a-number")

def test_search_request_search_mode_boundaries():
    from pydantic import ValidationError

    # Valid modes
    for mode in ["hybrid", "semantic", "lexical"]:
        r = SearchRequest(query="test", search_mode=mode)
        assert r.search_mode == mode

    # Invalid modes must be rejected by Literal schema validation
    for invalid in ["unknown", "HYBRID", "dense", "sparse", ""]:
        with pytest.raises(ValidationError):
            SearchRequest(query="test", search_mode=invalid)
