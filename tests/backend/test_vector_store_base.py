import pytest
from abc import ABC
from typing import List, Dict, Any, Optional, Tuple
from pydantic import ValidationError

from app.services.vector_store.base import (
    VectorStore,
    VectorDocument,
    VectorSearchResult,
)


class IncompleteVectorStore(VectorStore):
    """Incomplete subclass missing abstract methods."""
    def ensure_collection(self) -> bool:
        return True


class DummyVectorStore(VectorStore):
    """Concrete subclass implementing all abstract methods."""

    def ensure_collection(self) -> bool:
        return True

    def upsert_documents(self, documents: List[Any]) -> bool:
        return True

    def delete_by_path(self, filepath: str) -> bool:
        return True

    def delete_by_repo(self, repo_name: str) -> bool:
        return True

    def search(
        self,
        query_text: str,
        doc_type: Optional[str] = None,
        repo: Optional[str] = None,
        language: Optional[str] = None,
        category: Optional[str] = None,
        tag: Optional[str] = None,
        limit: int = 5,
    ) -> List[VectorSearchResult]:
        return [
            VectorSearchResult(
                id="dummy-1",
                score=0.95,
                payload={"repo": repo or "test-repo", "content": "sample content"}
            )
        ]

    def get_stats(self) -> Dict[str, Any]:
        return {"status": "ok", "count": 1}

    def health_check(self) -> Tuple[bool, str]:
        return True, "Healthy"


def test_cannot_instantiate_abstract_vector_store():
    """Verify VectorStore is an ABC and cannot be instantiated directly."""
    with pytest.raises(TypeError):
        VectorStore()


def test_incomplete_subclass_cannot_be_instantiated():
    """Verify a subclass missing abstract methods cannot be instantiated."""
    with pytest.raises(TypeError):
        IncompleteVectorStore()


def test_concrete_subclass_can_be_instantiated():
    """Verify concrete subclass implementing all methods works properly."""
    store = DummyVectorStore()
    assert store.ensure_collection() is True
    assert store.upsert_documents([]) is True
    assert store.delete_by_path("test/file.py") is True
    assert store.delete_by_repo("test-repo") is True
    
    results = store.search("test query", repo="my-repo", limit=3)
    assert len(results) == 1
    assert results[0].id == "dummy-1"
    assert results[0].score == 0.95
    assert results[0].payload["repo"] == "my-repo"

    stats = store.get_stats()
    assert stats["count"] == 1

    healthy, msg = store.health_check()
    assert healthy is True
    assert msg == "Healthy"


def test_vector_document_creation_defaults():
    """Verify VectorDocument creation with defaults."""
    doc = VectorDocument(id="doc-1", text="some code snippet")
    assert doc.id == "doc-1"
    assert doc.text == "some code snippet"
    assert doc.doc_type == "doc"
    assert doc.repo is None
    assert doc.path is None
    assert doc.rel_path is None
    assert doc.tags == []
    assert doc.metadata == {}
    assert doc.dense_vector is None
    assert doc.sparse_indices is None
    assert doc.sparse_values is None


def test_vector_document_full_fields():
    """Verify VectorDocument with all explicit fields."""
    doc = VectorDocument(
        id="chunk-123",
        text="def foo(): pass",
        dense_vector=[0.1, 0.2, 0.3],
        sparse_indices=[1, 5, 10],
        sparse_values=[0.5, 0.8, 0.2],
        repo="backend-api",
        path="/docs/repo/backend-api/app/main.py",
        rel_path="app/main.py",
        title="main.py",
        folder="app",
        category="python",
        tags=["fastapi", "core"],
        doc_type="code",
        language="python",
        heading="foo",
        symbol="foo",
        start_line=1,
        end_line=5,
        github_url="https://github.com/org/repo/blob/main/app/main.py#L1-L5",
        metadata={"extra_field": "custom_val"}
    )
    assert doc.id == "chunk-123"
    assert doc.language == "python"
    assert doc.tags == ["fastapi", "core"]
    assert doc.metadata["extra_field"] == "custom_val"

    payload = doc.to_payload()
    assert payload["repo"] == "backend-api"
    assert payload["path"] == "/docs/repo/backend-api/app/main.py"
    assert payload["rel_path"] == "app/main.py"
    assert payload["content"] == "def foo(): pass"
    assert payload["doc_type"] == "code"
    assert payload["language"] == "python"
    assert payload["symbol"] == "foo"
    assert payload["heading"] == "foo"
    assert payload["start_line"] == 1
    assert payload["end_line"] == 5
    assert payload["github_url"] == "https://github.com/org/repo/blob/main/app/main.py#L1-L5"
    assert payload["extra_field"] == "custom_val"


def test_vector_document_validation():
    """Verify required field validation in VectorDocument."""
    with pytest.raises(ValidationError):
        VectorDocument()  # missing required fields


def test_vector_search_result_creation_and_payload():
    """Verify VectorSearchResult creation and payload access."""
    result = VectorSearchResult(
        id="result-1",
        score=0.88,
        payload={
            "repo": "knowledge-rag-mcp",
            "rel_path": "README.md",
            "content": "Overview of RAG server",
            "tags": ["rag", "docs"],
            "github_url": "https://github.com/example/repo"
        }
    )
    assert result.id == "result-1"
    assert result.score == 0.88
    assert result.payload["repo"] == "knowledge-rag-mcp"
    assert result.payload["content"] == "Overview of RAG server"
    
    d = result.to_dict()
    assert d["id"] == "result-1"
    assert d["score"] == 0.88
    assert isinstance(d["payload"], dict)
