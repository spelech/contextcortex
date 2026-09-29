import pytest
from unittest.mock import patch, MagicMock
from app.services.search import execute_hybrid_search
from app.services.vector_store.base import VectorSearchResult

def test_execute_hybrid_search_empty_query():
    assert execute_hybrid_search("") == []
    assert execute_hybrid_search("   ") == []

def test_execute_hybrid_search_delegation():
    mock_hit = VectorSearchResult(
        id="test-id-1",
        score=0.92,
        payload={"repo": "my-repo", "content": "def test(): pass"}
    )
    with patch("app.services.search.get_vector_store") as mock_get_store:
        mock_store = MagicMock()
        mock_store.search.return_value = [mock_hit]
        mock_get_store.return_value = mock_store

        results = execute_hybrid_search(
            query_text="authentication",
            doc_type="code",
            repo="test-repo",
            language="python",
            category="core",
            tag="auth",
            limit=5
        )

        assert len(results) == 1
        assert results[0].id == "test-id-1"
        assert results[0].score == 0.92
        assert results[0].payload["repo"] == "my-repo"
        mock_store.search.assert_called_once_with(
            query_text="authentication",
            doc_type="code",
            repo="test-repo",
            language="python",
            category="core",
            tag="auth",
            limit=5
        )

def test_execute_hybrid_search_exception():
    with patch("app.services.search.get_vector_store") as mock_get_store:
        mock_store = MagicMock()
        mock_store.search.side_effect = Exception("Vector store backend down")
        mock_get_store.return_value = mock_store

        results = execute_hybrid_search("query")
        assert results == []


def test_execute_hybrid_search_end_to_end_real(tmp_path, monkeypatch):
    """
    Validates REAL hybrid retrieval without mocking get_vector_store or execute_hybrid_search.
    Asserts both Markdown and PDF docs are matched under doc_type='doc'.
    """
    from app.services.vector_store import get_vector_store, VectorStoreManager
    from app.services.vector_store.base import VectorDocument
    from app.services.database import set_vector_store_db_config

    qdrant_dir = str(tmp_path / "real_qdrant")
    set_vector_store_db_config(
        provider="qdrant",
        mode="embedded",
        storage_path=qdrant_dir,
        url="",
        collection="test_real_search",
    )
    VectorStoreManager.reset_instance()

    store = get_vector_store(force_reload=True)
    doc1 = VectorDocument(
        id="code-1",
        text="def authenticate_jwt_user(token: str): return True",
        repo="backend",
        doc_type="code",
        language="python",
        path="app/auth.py",
        rel_path="app/auth.py",
        title="auth.py",
        symbol="authenticate_jwt_user",
        start_line=1,
        end_line=2,
    )
    doc2 = VectorDocument(
        id="doc-1",
        text="ContextCortex Architecture Decision Record for Hybrid Search Retrieval",
        repo="docs",
        doc_type="doc",
        path="docs/adr/001-search.md",
        rel_path="docs/adr/001-search.md",
        title="001-search.md",
        heading="Architecture Decision",
        start_line=1,
        end_line=5,
    )
    doc3 = VectorDocument(
        id="pdf-1",
        text="Operator Manual and Deployment Runbook for ContextCortex Gateway",
        repo="ops",
        doc_type="pdf",
        path="docs/manual.pdf",
        rel_path="docs/manual.pdf",
        title="manual.pdf",
        heading="Page 1",
        start_line=1,
        end_line=1,
    )
    assert store.upsert_documents([doc1, doc2, doc3]) is True

    # 1. Search code
    code_results = execute_hybrid_search("authenticate user", doc_type="code")
    assert len(code_results) >= 1
    assert any(h.payload.get("symbol") == "authenticate_jwt_user" for h in code_results)

    # 2. Search doc -> should return Markdown doc
    doc_results = execute_hybrid_search("Architecture Decision", doc_type="doc")
    assert len(doc_results) >= 1
    assert any(h.payload.get("rel_path") == "docs/adr/001-search.md" for h in doc_results)

    # 3. Search doc -> should also find PDF doc!
    pdf_results = execute_hybrid_search("Deployment Runbook Operator Manual", doc_type="doc")
    assert len(pdf_results) >= 1
    assert any(h.payload.get("rel_path") == "docs/manual.pdf" for h in pdf_results)

