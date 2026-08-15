import logging
from typing import Optional, List, Any
from qdrant_client.http import models as qmodels
from app.services.embeddings import *
from app.services.indexer import qdrant, COLLECTION_NAME

logger = logging.getLogger('notes-rag-mcp')

def execute_hybrid_search(
    query_text: str,
    doc_type: Optional[str] = None,
    repo: Optional[str] = None,
    language: Optional[str] = None,
    category: Optional[str] = None,
    tag: Optional[str] = None,
    limit: int = 5
) -> List[Any]:
    """Executes Dense + BM25 Sparse hybrid search with Reciprocal Rank Fusion in Qdrant."""
    dense_vec = get_dense_embedding(query_text.strip())
    sparse_vec = get_sparse_embedding(query_text.strip())

    must_conditions = []
    if doc_type:
        must_conditions.append(qmodels.FieldCondition(key="doc_type", match=qmodels.MatchValue(value=doc_type)))
    if repo:
        must_conditions.append(qmodels.FieldCondition(key="repo", match=qmodels.MatchValue(value=repo)))
    if language:
        must_conditions.append(qmodels.FieldCondition(key="language", match=qmodels.MatchValue(value=language)))
    if category:
        must_conditions.append(qmodels.FieldCondition(key="category", match=qmodels.MatchValue(value=category)))
    if tag:
        must_conditions.append(qmodels.FieldCondition(key="tags", match=qmodels.MatchAny(any=[tag])))

    query_filter = qmodels.Filter(must=must_conditions) if must_conditions else None

    # Use RRF if sparse vector is available, otherwise dense search
    if sparse_vec is not None:
        response = qdrant.query_points(
            collection_name=COLLECTION_NAME,
            prefetch=[
                qmodels.Prefetch(
                    query=dense_vec,
                    using="dense",
                    limit=limit * 2,
                    filter=query_filter
                ),
                qmodels.Prefetch(
                    query=sparse_vec,
                    using="sparse",
                    limit=limit * 2,
                    filter=query_filter
                )
            ],
            query=qmodels.FusionQuery(fusion=qmodels.Fusion.RRF),
            limit=limit
        )
    else:
        response = qdrant.query_points(
            collection_name=COLLECTION_NAME,
            query=dense_vec,
            using="dense",
            query_filter=query_filter,
            limit=limit
        )
    return response.points
