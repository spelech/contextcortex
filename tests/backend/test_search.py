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

