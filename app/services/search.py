import logging
from typing import Optional, List
from app.services.vector_store import get_vector_store, VectorSearchResult

logger = logging.getLogger('contextcortex.search')


def execute_hybrid_search(
    query_text: str,
    doc_type: Optional[str] = None,
    repo: Optional[str] = None,
    language: Optional[str] = None,
    category: Optional[str] = None,
    tag: Optional[str] = None,
    limit: int = 5
) -> List[VectorSearchResult]:
    """Executes vector search via the configured active VectorStore backend."""
    if not query_text or not query_text.strip():
        return []

    try:
        store = get_vector_store()
        return store.search(
            query_text=query_text.strip(),
            doc_type=doc_type,
            repo=repo,
            language=language,
            category=category,
            tag=tag,
            limit=limit
        )
    except Exception as e:
        logger.error(f"Error executing vector search: {e}")
        return []

