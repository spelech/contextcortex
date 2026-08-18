import os
import uuid
import pytest
from unittest.mock import MagicMock, patch
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from app.services.vector_store.base import VectorDocument, VectorSearchResult, VectorStore
from app.services.vector_store.qdrant_store import QdrantVectorStore


class TestQdrantVectorStoreInit:
    """Tests for initialization, modes (remote vs embedded), and auto-fallback."""

    def test_init_in_memory_or_embedded(self, tmp_path):
        storage_path = str(tmp_path / "qdrant_db")
        store = QdrantVectorStore(
            storage_path=storage_path,
            collection_name="test_embedded_coll",
            prefer_remote=False
        )
        assert store.mode == "embedded"
        assert store.location == storage_path
        assert isinstance(store, VectorStore)
        assert store.client.collection_exists("test_embedded_coll")

    def test_init_remote_success(self):
        mock_client = MagicMock(spec=QdrantClient)
        mock_client.get_collections.return_value = MagicMock(collections=[])
        mock_client.collection_exists.return_value = False

        with patch("app.services.vector_store.qdrant_store.QdrantClient", return_value=mock_client):
            store = QdrantVectorStore(
                url="http://remote-qdrant:6333",
                collection_name="test_remote_coll",
                prefer_remote=True
            )
            assert store.mode == "remote"
            assert store.location == "http://remote-qdrant:6333"
            mock_client.get_collections.assert_called()

    def test_init_remote_fallback_to_embedded_on_connection_error(self, tmp_path):
        fallback_path = str(tmp_path / "fallback_qdrant")

        def side_effect(*args, **kwargs):
            if "url" in kwargs or (args and isinstance(args[0], str) and args[0].startswith("http")):
                raise ConnectionError("Cannot reach remote server")
            return QdrantClient(location=":memory:")

        with patch("app.services.vector_store.qdrant_store.QdrantClient", side_effect=side_effect):
            store = QdrantVectorStore(
                url="http://broken-remote:6333",
                storage_path=fallback_path,
                collection_name="test_fallback_coll",
                prefer_remote=True
            )
            assert store.mode in ("embedded", "memory")
            assert store.location == fallback_path
            assert store.client is not None

    def test_custom_injected_client(self):
        custom_client = QdrantClient(location=":memory:")
        store = QdrantVectorStore(
            client=custom_client,
            collection_name="test_custom_coll"
        )
        assert store.client is custom_client
        assert store.client.collection_exists("test_custom_coll")


class TestQdrantVectorStoreOperations:
    """Tests for ensure_collection, upsert, search, delete, stats, and health checks."""

    @pytest.fixture
    def memory_store(self):
        client = QdrantClient(location=":memory:")
        store = QdrantVectorStore(
            client=client,
            collection_name="test_ops_coll",
            auto_init=True
        )
        return store

    def test_ensure_collection_recreates_on_schema_mismatch(self, memory_store):
        # Create a single vector collection (legacy schema)
        memory_store.client.delete_collection("test_ops_coll")
        memory_store.client.create_collection(
            collection_name="test_ops_coll",
            vectors_config=qmodels.VectorParams(size=384, distance=qmodels.Distance.COSINE)
        )
        # Calling ensure_collection should detect legacy schema and upgrade to named vectors
        success = memory_store.ensure_collection()
        assert success is True

        info = memory_store.client.get_collection("test_ops_coll")
        assert "dense" in info.config.params.vectors
        assert info.config.params.sparse_vectors is not None
        assert "sparse" in info.config.params.sparse_vectors

    def test_upsert_vector_documents(self, memory_store):
        doc1 = VectorDocument(
            id=str(uuid.uuid4()),
            text="Antigravity is an advanced coding agent by DeepMind.",
            dense_vector=[0.1] * 384,
            sparse_indices=[10, 20],
            sparse_values=[0.5, 0.8],
            repo="core-agent",
            path="/docs/intro.md",
            doc_type="doc",
            language="markdown",
            tags=["deepmind", "ai"]
        )
        doc2 = VectorDocument(
            id=str(uuid.uuid4()),
            text="def compute_embeddings(text: str): pass",
            dense_vector=[0.2] * 384,
            sparse_indices=[30, 40],
            sparse_values=[0.7, 0.9],
            repo="core-agent",
            path="/src/embeddings.py",
            doc_type="code",
            language="python",
            tags=["python"]
        )

        ok = memory_store.upsert_documents([doc1, doc2])
        assert ok is True

        stats = memory_store.get_stats()
        assert stats["points_count"] == 2

    def test_upsert_chunked_batching(self, memory_store):
        docs = [
            VectorDocument(
                id=str(uuid.uuid4()),
                text=f"Batch document text number {i}",
                dense_vector=[0.01 * (i % 10)] * 384,
                sparse_indices=[i % 50],
                sparse_values=[1.0],
                repo="batch-test",
                path=f"/path/doc_{i}.md"
            )
            for i in range(250)
        ]
        with patch.object(memory_store.client, "upsert", wraps=memory_store.client.upsert) as spy_upsert:
            ok = memory_store.upsert_documents(docs, batch_size=100)
            assert ok is True
            assert spy_upsert.call_count == 3
            assert memory_store.get_stats()["points_count"] == 250

    def test_upsert_failure_handling_and_logging(self, memory_store):
        doc = VectorDocument(
            id=str(uuid.uuid4()),
            text="Failure simulation document",
            repo="fail-test",
            path="/fail/doc.md"
        )
        with patch.object(memory_store.client, "upsert", side_effect=RuntimeError("Qdrant connection dropped")):
            ok = memory_store.upsert_documents([doc])
            assert ok is False

    def test_upsert_dict_documents_auto_computes_vectors(self, memory_store):
        raw_doc = {
            "id": "non-uuid-custom-id",
            "text": "Self-healing collections and auto-fallback in Qdrant.",
            "repo": "infra-repo",
            "path": "/infra/qdrant.md",
            "doc_type": "doc",
            "language": "markdown"
        }
        ok = memory_store.upsert_documents([raw_doc])
        assert ok is True

        stats = memory_store.get_stats()
        assert stats["points_count"] == 1

    def test_search_dense_and_hybrid_rrf(self, memory_store):
        doc_ai = VectorDocument(
            id=str(uuid.uuid4()),
            text="Deep learning architectures and transformer attention mechanisms.",
            repo="ai-research",
            path="/docs/transformers.md",
            doc_type="doc",
            tags=["ml"]
        )
        doc_db = VectorDocument(
            id=str(uuid.uuid4()),
            text="Distributed vector search indexing using Qdrant and HNSW graphs.",
            repo="infra",
            path="/docs/vector_db.md",
            doc_type="doc",
            tags=["database"]
        )
        memory_store.upsert_documents([doc_ai, doc_db])

        # Search with matching query
        results = memory_store.search("Qdrant vector search indexing", limit=5)
        assert len(results) > 0
        assert isinstance(results[0], VectorSearchResult)
        assert results[0].payload["repo"] == "infra"
        assert results[0].score > 0

        # Filtered search
        filtered = memory_store.search("transformer", repo="ai-research", limit=5)
        assert len(filtered) > 0
        assert filtered[0].payload["repo"] == "ai-research"

        empty_filtered = memory_store.search("transformer", repo="non-existent", limit=5)
        assert len(empty_filtered) == 0

        # Empty query returns empty list
        assert memory_store.search("") == []

    def test_delete_by_path(self, memory_store):
        doc1 = VectorDocument(
            id=str(uuid.uuid4()),
            text="Content in path A",
            repo="repo-a",
            path="/path/a.md"
        )
        doc2 = VectorDocument(
            id=str(uuid.uuid4()),
            text="Content in path B",
            repo="repo-a",
            path="/path/b.md"
        )
        memory_store.upsert_documents([doc1, doc2])
        assert memory_store.get_stats()["points_count"] == 2

        ok = memory_store.delete_by_path("/path/a.md")
        assert ok is True
        assert memory_store.get_stats()["points_count"] == 1

        results = memory_store.search("Content in path A")
        for res in results:
            assert res.payload.get("path") != "/path/a.md"

    def test_delete_by_repo(self, memory_store):
        doc1 = VectorDocument(
            id=str(uuid.uuid4()),
            text="Repo X document",
            repo="repo-x",
            path="/repo-x/doc.md"
        )
        doc2 = VectorDocument(
            id=str(uuid.uuid4()),
            text="Repo Y document",
            repo="repo-y",
            path="/repo-y/doc.md"
        )
        memory_store.upsert_documents([doc1, doc2])
        assert memory_store.get_stats()["points_count"] == 2

        ok = memory_store.delete_by_repo("repo-x")
        assert ok is True
        assert memory_store.get_stats()["points_count"] == 1

        results = memory_store.search("Repo X document")
        for res in results:
            assert res.payload.get("repo") != "repo-x"

    def test_get_stats_and_health_check(self, memory_store):
        stats = memory_store.get_stats()
        assert stats["backend"] == "qdrant"
        assert "points_count" in stats
        assert stats["exists"] is True

        is_healthy, msg = memory_store.health_check()
        assert is_healthy is True
        assert "healthy" in msg
