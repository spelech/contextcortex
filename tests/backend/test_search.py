import pytest
from unittest.mock import patch, MagicMock
from app.services.search import execute_hybrid_search

def test_execute_hybrid_search_empty_query():
    assert execute_hybrid_search("") == []
    assert execute_hybrid_search("   ") == []

def test_execute_hybrid_search_collection_missing():
    with patch("app.services.search.qdrant") as mock_qdrant:
        mock_qdrant.collection_exists.return_value = False
        assert execute_hybrid_search("query") == []

def test_execute_hybrid_search_collection_exception():
    with patch("app.services.search.qdrant") as mock_qdrant:
        mock_qdrant.collection_exists.side_effect = Exception("Qdrant error")
        assert execute_hybrid_search("query") == []

def test_execute_hybrid_search_with_sparse():
    with patch("app.services.search.qdrant") as mock_qdrant, \
         patch("app.services.search.get_dense_embedding", return_value=[0.1, 0.2]), \
         patch("app.services.search.get_sparse_embedding", return_value={"indices": [1], "values": [0.5]}):
        
        mock_qdrant.collection_exists.return_value = True
        mock_hit = MagicMock()
        mock_hit.score = 0.08
        mock_response = MagicMock()
        mock_response.points = [mock_hit]
        mock_qdrant.query_points.return_value = mock_response

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
        assert results[0].score == 0.08
        mock_qdrant.query_points.assert_called_once()

def test_execute_hybrid_search_without_sparse():
    with patch("app.services.search.qdrant") as mock_qdrant, \
         patch("app.services.search.get_dense_embedding", return_value=[0.1, 0.2]), \
         patch("app.services.search.get_sparse_embedding", return_value=None):
        
        mock_qdrant.collection_exists.return_value = True
        mock_hit = MagicMock()
        mock_hit.score = 0.95
        mock_response = MagicMock()
        mock_response.points = [mock_hit]
        mock_qdrant.query_points.return_value = mock_response

        results = execute_hybrid_search(
            query_text="query without sparse",
            limit=3
        )

        assert len(results) == 1
        assert results[0].score == 0.95
