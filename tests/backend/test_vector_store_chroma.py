import os
import uuid
import pytest
from unittest.mock import MagicMock, patch
import chromadb

from app.services.vector_store.base import VectorDocument, VectorSearchResult, VectorStore
from app.services.vector_store.chroma_store import ChromaVectorStore


class TestChromaVectorStoreInit:
    """Tests for ChromaVectorStore initialization, storage modes, and remote fallback."""

    def test_init_in_memory(self):
        coll_name = f"test_mem_{uuid.uuid4().hex[:8]}"
        store = ChromaVectorStore(
            storage_path=":memory:",
            collection_name=coll_name,
            prefer_remote=False
        )
        assert store.mode == "memory"
        assert store.location == ":memory:"
        assert isinstance(store, VectorStore)
        assert store.collection is not None
        assert store.collection.name == coll_name

    def test_init_persistent_disk(self, tmp_path):
        storage_path = str(tmp_path / "chroma_db")
        coll_name = f"test_pers_{uuid.uuid4().hex[:8]}"
        store = ChromaVectorStore(
            storage_path=storage_path,
            collection_name=coll_name,
            prefer_remote=False
        )
        assert store.mode == "persistent"
        assert store.location == storage_path
        assert isinstance(store, VectorStore)
        assert store.collection is not None
        assert store.collection.name == coll_name
        assert os.path.exists(storage_path)

    def test_init_remote_success(self):
        mock_client = MagicMock()
        mock_client.heartbeat.return_value = 123456
        mock_coll = MagicMock()
        mock_coll.name = "test_remote_coll"
        mock_coll.count.return_value = 0
        mock_client.get_or_create_collection.return_value = mock_coll

        with patch("app.services.vector_store.chroma_store.chromadb.HttpClient", return_value=mock_client):
            store = ChromaVectorStore(
                host="remote-chroma",
                port=8000,
                collection_name="test_remote_coll",
                prefer_remote=True
            )
            assert store.mode == "remote"
            assert "remote-chroma" in store.location
            mock_client.heartbeat.assert_called_once()

    def test_init_remote_fallback_to_persistent_on_error(self, tmp_path):
        fallback_path = str(tmp_path / "fallback_chroma")
        coll_name = f"test_fb_{uuid.uuid4().hex[:8]}"

        with patch("app.services.vector_store.chroma_store.chromadb.HttpClient", side_effect=ValueError("Could not connect")):
            store = ChromaVectorStore(
                host="broken-chroma",
                port=8000,
                storage_path=fallback_path,
                collection_name=coll_name,
                prefer_remote=True
            )
            assert store.mode == "persistent"
            assert store.location == fallback_path
            assert store.client is not None
            assert store.collection is not None

    def test_custom_injected_client(self):
        custom_client = chromadb.EphemeralClient()
        coll_name = f"test_cust_{uuid.uuid4().hex[:8]}"
        store = ChromaVectorStore(
            client=custom_client,
            collection_name=coll_name
        )
        assert store.client is custom_client
        assert store.mode == "custom"
        assert store.collection.name == coll_name


class TestChromaVectorStoreOperations:
    """Tests for ChromaVectorStore operations: upsert, search, metadata filtering, delete, stats, health."""

    @pytest.fixture
    def memory_store(self):
        client = chromadb.EphemeralClient()
        coll_name = f"test_ops_{uuid.uuid4().hex[:8]}"
        store = ChromaVectorStore(
            client=client,
            collection_name=coll_name,
            auto_init=True
        )
        yield store
        try:
            client.delete_collection(coll_name)
        except Exception:
            pass

    def test_ensure_collection(self, memory_store):
        ok = memory_store.ensure_collection()
        assert ok is True
        assert memory_store.collection is not None
        assert memory_store.collection.name == memory_store.collection_name

    def test_upsert_vector_documents(self, memory_store):
        doc1 = VectorDocument(
            id="doc-uuid-1",
            text="Antigravity is an advanced coding assistant by DeepMind.",
            dense_vector=[0.1] * 384,
            repo="core-agent",
            path="/docs/intro.md",
            doc_type="doc",
            language="markdown",
            tags=["deepmind", "ai"]
        )
        doc2 = VectorDocument(
            id="doc-uuid-2",
            text="def compute_embeddings(text: str): pass",
            dense_vector=[0.2] * 384,
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

    def test_upsert_dict_documents_auto_computes_vectors(self, memory_store):
        raw_doc = {
            "id": "dict-doc-1",
            "text": "ChromaDB vector store with dense cosine embeddings.",
            "repo": "infra-repo",
            "path": "/infra/chroma.md",
            "doc_type": "doc",
            "language": "markdown"
        }
        ok = memory_store.upsert_documents([raw_doc])
        assert ok is True

        stats = memory_store.get_stats()
        assert stats["points_count"] == 1

    def test_upsert_handles_complex_metadata(self, memory_store):
        doc = {
            "id": "complex-doc-1",
            "text": "Document with edge cases in metadata fields.",
            "repo": "test-repo",
            "path": "/test/complex.md",
            "none_field": None,
            "empty_tags": [],
            "tags": ["alpha", "beta"],
            "nested_dict": {"k": "v"},
            "start_line": 10,
            "end_line": 20,
        }
        ok = memory_store.upsert_documents([doc])
        assert ok is True
        assert memory_store.get_stats()["points_count"] == 1

    def test_search_dense(self, memory_store):
        doc_ai = VectorDocument(
            id="doc-ai-1",
            text="Deep learning transformer architectures and attention heads.",
            repo="ai-research",
            path="/docs/transformers.md",
            doc_type="doc",
            tags=["ml"]
        )
        doc_db = VectorDocument(
            id="doc-db-1",
            text="Distributed vector search indexing using Chroma and HNSW graphs.",
            repo="infra",
            path="/docs/vector_db.md",
            doc_type="doc",
            tags=["database"]
        )
        memory_store.upsert_documents([doc_ai, doc_db])

        results = memory_store.search("Chroma vector search indexing", limit=5)
        assert len(results) > 0
        assert isinstance(results[0], VectorSearchResult)
        assert results[0].payload["repo"] == "infra"
        assert results[0].score > 0

        # Empty query
        assert memory_store.search("") == []

    def test_search_metadata_filtering(self, memory_store):
        doc1 = VectorDocument(
            id="f-doc-1",
            text="Python async programming with asyncio event loops.",
            repo="repo-python",
            path="/src/async.py",
            doc_type="code",
            language="python",
            category="backend",
            tags=["async", "concurrency"]
        )
        doc2 = VectorDocument(
            id="f-doc-2",
            text="React functional components and hooks guide.",
            repo="repo-frontend",
            path="/src/components.tsx",
            doc_type="code",
            language="typescript",
            category="frontend",
            tags=["react", "ui"]
        )
        doc3 = VectorDocument(
            id="f-doc-3",
            text="Architecture decision record for backend data storage.",
            repo="repo-python",
            path="/docs/adr.md",
            doc_type="doc",
            language="markdown",
            category="backend",
            tags=["architecture"]
        )
        memory_store.upsert_documents([doc1, doc2, doc3])

        # Filter by repo
        res_repo = memory_store.search("programming", repo="repo-python", limit=5)
        assert len(res_repo) > 0
        for r in res_repo:
            assert r.payload["repo"] == "repo-python"

        # Filter by doc_type
        res_doc_type = memory_store.search("architecture", doc_type="doc", limit=5)
        assert len(res_doc_type) > 0
        for r in res_doc_type:
            assert r.payload["doc_type"] == "doc"

        # Filter by language
        res_lang = memory_store.search("components", language="typescript", limit=5)
        assert len(res_lang) > 0
        for r in res_lang:
            assert r.payload["language"] == "typescript"

        # Filter by category
        res_cat = memory_store.search("storage", category="backend", limit=5)
        assert len(res_cat) > 0
        for r in res_cat:
            assert r.payload["category"] == "backend"

        # Filter by tag
        res_tag = memory_store.search("react", tag="react", limit=5)
        assert len(res_tag) > 0
        for r in res_tag:
            assert "react" in r.payload["tags"]

        # Combined multi-filter
        res_multi = memory_store.search("async", repo="repo-python", doc_type="code", category="backend", limit=5)
        assert len(res_multi) > 0
        assert res_multi[0].id == "f-doc-1"

        # Non-matching filter returns empty
        res_empty = memory_store.search("async", repo="non-existent", limit=5)
        assert len(res_empty) == 0

    def test_delete_by_path(self, memory_store):
        doc1 = VectorDocument(
            id="del-path-1",
            text="Content in path A",
            repo="repo-a",
            path="/path/a.md"
        )
        doc2 = VectorDocument(
            id="del-path-2",
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
            id="del-repo-1",
            text="Repo X document content",
            repo="repo-x",
            path="/repo-x/doc.md"
        )
        doc2 = VectorDocument(
            id="del-repo-2",
            text="Repo Y document content",
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
        assert stats["backend"] == "chroma"
        assert stats["points_count"] == 0
        assert stats["exists"] is True

        is_healthy, msg = memory_store.health_check()
        assert is_healthy is True
        assert "healthy" in msg
