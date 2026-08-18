from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Tuple, Union
from pydantic import BaseModel, Field


class VectorDocument(BaseModel):
    """Represents a document chunk with vector embeddings and metadata."""
    id: str
    text: str
    dense_vector: Optional[List[float]] = None
    sparse_indices: Optional[List[int]] = None
    sparse_values: Optional[List[float]] = None
    repo: Optional[str] = None
    path: Optional[str] = None
    rel_path: Optional[str] = None
    title: Optional[str] = None
    folder: Optional[str] = None
    category: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    doc_type: str = "doc"
    language: Optional[str] = None
    heading: Optional[str] = None
    symbol: Optional[str] = None
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    github_url: Optional[str] = None
    permalink_url: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        if self.permalink_url is None and self.github_url is not None:
            self.permalink_url = self.github_url
        elif self.github_url is None and self.permalink_url is not None:
            self.github_url = self.permalink_url

    def to_payload(self) -> Dict[str, Any]:
        """Converts the document to a standard dictionary payload."""
        effective_url = self.permalink_url or self.github_url
        payload: Dict[str, Any] = {
            "repo": self.repo,
            "doc_type": self.doc_type,
            "path": self.path,
            "rel_path": self.rel_path,
            "title": self.title,
            "folder": self.folder,
            "category": self.category,
            "tags": self.tags,
            "heading": self.heading,
            "symbol": self.symbol,
            "language": self.language,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "github_url": effective_url,
            "permalink_url": effective_url,
            "content": self.text,
        }
        if self.metadata:
            payload.update(self.metadata)
        return payload

    @property
    def payload(self) -> Dict[str, Any]:
        """Convenience property to access payload dictionary."""
        return self.to_payload()




class VectorSearchResult(BaseModel):
    """Represents a ranked search result item returned from a vector store."""
    id: str
    score: float = 0.0
    payload: Dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Converts result to a dictionary."""
        return {
            "id": self.id,
            "score": self.score,
            "payload": self.payload
        }


class VectorStore(ABC):
    """Abstract base class for vector store backends."""

    @abstractmethod
    def ensure_collection(self) -> bool:
        """Initializes or validates the collection schema."""
        pass

    @abstractmethod
    def upsert_documents(
        self,
        documents: List[Union[VectorDocument, Dict[str, Any]]],
        batch_size: int = 100
    ) -> bool:
        """Upserts a batch of document chunks with vectors and payload."""
        pass

    @abstractmethod
    def delete_by_path(self, filepath: str) -> bool:
        """Purges vectors associated with a specific file path."""
        pass

    @abstractmethod
    def delete_by_repo(self, repo_name: str) -> bool:
        """Purges all vectors belonging to a repository."""
        pass

    @abstractmethod
    def search(
        self,
        query_text: str,
        doc_type: Optional[str] = None,
        repo: Optional[str] = None,
        language: Optional[str] = None,
        category: Optional[str] = None,
        tag: Optional[str] = None,
        limit: int = 5
    ) -> List[VectorSearchResult]:
        """Performs vector search returning ranked results."""
        pass

    @abstractmethod
    def get_stats(self) -> Dict[str, Any]:
        """Returns collection info including point count, backend, and mode."""
        pass

    @abstractmethod
    def health_check(self) -> Tuple[bool, str]:
        """Validates connection and readiness of the backend."""
        pass

    def close(self):
        """Optional hook to cleanly close underlying client/storage handles."""
        pass

